import hashlib
import auth_public as auth

import psycopg2, psycopg2.extensions, psycopg2.extras
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE) # se znebimo problemov s šumniki

from typing import List, TypeVar, Type
from modeli import *
from csv import reader
from re import sub, findall
from datetime import date
from pandas import DataFrame
from dataclasses import fields
import os

DB_PORT = os.environ.get('POSTGRES_PORT', 5432)

# Ustvarimo generično TypeVar spremenljivko. Dovolimo le naše entitene, ki jih imamo tudi v bazi
# kot njene vrednosti. Ko dodamo novo entiteno, jo moramo dodati tudi v to spremenljivko.
T = TypeVar(
    'T',
    app_user,
    pair,
    price_history,
    asset,
    trade
    )

class Repo:

    def __init__(self):
        self.conn = psycopg2.connect(database=auth.db, host=auth.host, user=auth.user, password=auth.password, port=DB_PORT)
        self.cur = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)


    def dobi_gen_id(self, typ: Type[T], id: int | str, id_col = 'id') -> T:
        ''' Generična metoda, ki vrne dataclass objekt 
            pridobljen iz baze na podlagi njegovega idja. '''
        tbl_name = typ.__name__
        sql_cmd = f'SELECT * FROM {tbl_name} WHERE {id_col} = %s';
        try:
            self.cur.execute(sql_cmd, (id,))
            d = self.cur.fetchone()
        except:
            self.conn.rollback()
            raise Exception(f'Vrstica z id-jem {id} ne obstaja v {tbl_name}');
        return d


    def dodaj_gen(self, typ: T, serial_col='id', auto_commit=True):
        ''' Generična metoda, ki v bazo doda entiteto/objekt. 
            V kolikor imamo definiran serial stolpec,
            objektu to vrednost tudi nastavimo. '''
        tbl_name = type(typ).__name__

        cols =[c.name for c in fields(typ) if c.name != serial_col]
        
        sql_cmd = f'''
            INSERT INTO {tbl_name} ({', '.join(cols)})
            VALUES
            ({self.cur.mogrify(','.join(['%s']*len(cols)), [getattr(typ, c) for c in cols]).decode('utf-8')})
        '''

        if serial_col != None:
            sql_cmd += f'RETURNING {serial_col}'

        self.cur.execute(sql_cmd)

        if serial_col != None:
            serial_val = self.cur.fetchone()[0]

            # Nastavimo vrednost serial stolpca
            setattr(typ, serial_col, serial_val)

        if auto_commit: self.conn.commit()
      

    ########################################################################
    #######################       USER       ###############################
    ########################################################################

    def get_user(self, user_id: int) -> list:
        self.cur.execute('''
            SELECT name, surname, date_of_birth, user_name, password 
            FROM app_user
            WHERE id_user = %s
        ''', (user_id,))
        return self.cur.fetchone()


    def posodobi_user(self, user_id: int, ime: str, priimek: str, datum: date, geslo: str):
        if geslo != '':
            h = hashlib.blake2b()
            h.update(geslo.encode(encoding='utf-8'))
            hash = h.hexdigest()
            self.cur.execute('''
                UPDATE app_user
                SET name = %s, surname = %s, date_of_birth =  %s,  password = %s
                WHERE id_user = %s; 
            ''', (ime, priimek, datum, hash, user_id,))
        else:
            self.cur.execute('''
                    UPDATE app_user
                    SET name = %s, surname = %s, date_of_birth =  %s
                    WHERE id_user = %s; 
                ''', (ime, priimek, datum, user_id,))
        self.conn.commit()

    ########################################################################
    ######################       ASSETS       ##############################
    ########################################################################

    def uvozi_Price_History(self, tabela: str):
        ''' Vnese zgodovino simbola v tabelo price_history '''
        with open('Podatki/Posamezni_simboli/{0}'.format(tabela)) as csvfile:
            podatki = reader(csvfile)
            next(podatki)
            for r in podatki:
                r = [None if x in ('', '-') else x for x in r]
                self.cur.execute('''
                    INSERT INTO price_history
                    (symbol_id, date, price)
                    VALUES (%s, %s, %s)
                ''', r)
            self.conn.commit()
            print('Uspesno uvozil csv datoteko!')


    def dodaj_par(self, simbol: str, name: str) -> int:
        try:
            self.cur.execute('''
                INSERT INTO pair (symbol, name) 
                VALUES (%s, %s)
            ''', (simbol, name))
            self.conn.commit()
            return 1
        except:
            self.conn.rollback()
            return 0


    def posodobi_price_history(self, df: DataFrame | None):
        if not df is None:
            for i in df.index:
                if df['price'][i] != 'NaN':
                    self.cur.execute('''
                        INSERT INTO price_history (symbol_id, date, price)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (symbol_id, date)
                        DO UPDATE SET price = {}
                    '''.format(df['price'][i]), (df['symbol_id'][i], df['date'][i], df['price'][i]))
            self.conn.commit()
            

    def dobi_asset_by_user(self, id: int) -> List[str]:
        self.cur.execute('''
            SELECT * 
            FROM asset 
            WHERE user_id = %s
        ''', (id,))
        d = self.cur.fetchall()

        seznam = list()
        for i in d:
            seznam.append(i[1])
        return seznam
    

    def dobi_asset_amount_by_user(self, user_id: int) -> List[List]:
        self.cur.execute('''
            SELECT symbol_id, amount
            FROM asset
            WHERE user_id = %s
        ''', (user_id,))
        return self.cur.fetchall()
    

    def dobi_pare(self) -> List[List]:
        self.cur.execute('''
            SELECT symbol, name
            FROM pair
        ''')
        return self.cur.fetchall()


    ########################################################################
    ######################       TRADES       ##############################
    ########################################################################

    def dobi_strategije(self, user_id: int) -> List[str]:
        self.cur.execute('''
            SELECT strategy 
            FROM trade
            WHERE user_id = {} 
            AND (type = 'L' OR type = 'S') 
            GROUP BY strategy
        '''.format(user_id))
        zacasni = self.cur.fetchall()
        seznam = list()
        for item in zacasni:
            seznam.append(item[0])
        return seznam


    def sign(self, amount: float | str, tip: str) -> float:
        amount = float(amount)
    # Določi predznak
        if tip == 'Sell':
            return -abs(amount)
        return abs(amount)


    def trade_result(self, user_id: int, simbol: str, pnl: float):
        self.cur.execute('''
            SELECT amount 
            FROM asset
            WHERE user_id = '{0}' 
            AND symbol_id = '{1}'
        '''.format(user_id, simbol))
        row = self.cur.fetchone()
        if row is None:
            self.cur.execute('''
                INSERT INTO asset (user_id, symbol_id, amount) 
                VALUES (%s, %s, %s)
            ''', (user_id, simbol, pnl))
        else:
            amount = round(pnl + float(row[0]), 2)
            self.cur.execute('''
                UPDATE  asset 
                SET amount = {0} 
                WHERE user_id = '{1}' 
                AND symbol_id = '{2}'
            '''.format(amount, user_id, simbol))
        self.conn.commit()


    def dobi_trade_delno(self, user_id: int, column='symbol_id') -> List[T]:
        ''' Če podamo stoplec nam seznam uredi glede na ta stolpec '''
        self.cur.execute('''
            SELECT id_trade, symbol_id, type, strategy, RR, target, date, duration, TP, PNL 
            FROM trade
            WHERE user_id = {} 
            ORDER BY {} 
        '''.format(user_id, column))
        return self.cur.fetchall()


    def pnl_trade(self, user_id: int, simbol: str, pnl: float | str, brisi=False):
        dollar = findall(r'\$', pnl)
            
        if dollar == []:    # PNL doda pri assetu na katerem je trade
            if brisi == True:
                pnl = -float(pnl)
            Repo().trade_result(user_id, simbol, float(pnl))
        
        elif dollar != []:  # PNL doda pri USD
            pnl = sub('\$','',pnl)
            if brisi == True:
                pnl = -float(pnl)
            Repo().trade_result(user_id, 'USD', float(pnl))


    def izbrisi_trade(self, trade_id: int):

        # Preračuna asset
        self.cur.execute('''
            SELECT user_id, symbol_id, pnl 
            FROM trade
            WHERE id_trade = %s
        ''', (trade_id,))
        trade = self.cur.fetchone()
        Repo().pnl_trade(trade[0], trade[1], trade[2], True)

        # Izbriše trade iz baze
        self.cur.execute('''
                DELETE FROM  trade
                WHERE id_trade = %s 
            ''', (trade_id,))
        self.conn.commit()
