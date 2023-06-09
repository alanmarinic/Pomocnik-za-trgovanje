from datetime import date
import re
import pandas as pd
import plotly.express as px

from auth_public import *
import auth_public as auth

import psycopg2, psycopg2.extensions, psycopg2.extras
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)

# Prepreči izpisovanje SQLAlcemy opozorila v terminal
import warnings
warnings.filterwarnings('ignore')

conn = psycopg2.connect(database=auth.db, host=auth.host, user=auth.user, password=auth.password, port=5432)
cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

trade_data = pd.read_sql('SELECT user_id, symbol_id, type, date, pnl FROM trade', conn)
price_data = pd.read_sql('SELECT * FROM price_history', conn)

from typing import List, Tuple

class Graf:

    def filter_by_row(self, df: pd.DataFrame, column: str, filter_list: List[str]) -> pd.DataFrame:
        ''' Vrne df, samo z vrsticami, ki imajo v stolpcu column
            eno izmed vrednosti s seznama filter_list '''
        seznam = list()
        for row in df.index:
            drop_item = True
            for value in filter_list:
                if df[column][row] == value:
                    drop_item = False
            if drop_item == True:
                seznam.append(row)   
        df = df.drop(seznam)
        df = df.reset_index(drop=True)
        return df


    def datumi(self) -> pd.DataFrame:
        ''' Vrne df z vsemi možnimi datumi in stolpcem z 0 '''
        df = Graf().filter_by_row(price_data, 'symbol_id', ['BTC-USD'])
        df = df.drop(['symbol_id', 'price'], axis=1)
        df = df.reset_index(drop=True)
        df['price'] = [0] * len(df.index)
        return df


    def pnl_type(self, df: pd.DataFrame, usd=False) -> pd.DataFrame:
        ''' Funkcija vrne le trade, ki imajo PNL v istem assetu kot je trade.
            PNL je velikokrat lahko tudi v USD, toda v tem primeru moram PNL 
            računati pri USD namest pri pripadajočem assetu '''
        bad_index = list()
        for i in df.index:
            pnl = re.findall(r'\d+(?:\.\d+)?\$', df['pnl'][i])
            if usd == False:
                if pnl != []:
                    bad_index.append(i)
            else:
                if pnl == []:
                    bad_index.append(i)
        df = df.drop(bad_index)

        if usd == True:
            df = Graf().clean_sign(df)
        df['pnl'] = pd.to_numeric(df['pnl'])
        return df
    

    def clean_sign(self, df: pd.DataFrame) -> pd.DataFrame:
        ''' Odstrani znak $ iz stoplca pnl '''
        for row in df.index:
            pnl = re.findall(r'(?:-)?\d+(?:\.\d+)?\$', df['pnl'][row])
            if pnl != []:
                pnl = re.sub('\$','',pnl[0])
                df.loc[row, 'pnl'] = pnl
        return df


    def pripravi_trade_data(self, id_user: int, symbol_id: str, usd=False) -> pd.DataFrame:
        ''' Za izbranega uporabnika in izbran simbol vrne df
            s stoplci date, symbol_id, pnl '''
        df = trade_data
        df = Graf().filter_by_row(df, 'user_id', [id_user])
        if symbol_id != 'dollar':
            df = Graf().filter_by_row(df, 'symbol_id', [symbol_id])

        df = df.drop(['user_id', 'type', 'symbol_id'], axis=1)
        df = Graf().pnl_type(df, usd)
        df = df.groupby('date', as_index=False).sum()
        return df


    def fix_stocks(self, symbol_id: str) -> pd.DataFrame:
        ''' Zgodovina delnic je brez vikendov in praznikov, ta funkcija
            generira 'realne podatke' in jih vstavi '''
        stock = Graf().filter_by_row(price_data, 'symbol_id', [symbol_id])
        df = Graf().datumi()

        if len(stock) < len(df):
            # Vstavi ceno 0 za dni, ki niso definirani
            for row in df.index:
                for i in stock.index:
                    if df['date'][row] == stock['date'][i]:
                        df.loc[row, 'price'] = stock['price'][i]

            # Popravi ceno, kjer je ta 0, da bo graf zvezen
            if len(stock) > 0:
                for row in df.index:
                    i = 1
                    while df['price'][row] == 0:
                        if row < (len(df) - 3):
                            try:
                                df.loc[row, 'price'] = df['price'][row + i]
                            except KeyError or ValueError:
                                df.loc[row, 'price'] = 0
                        elif row > (len(df) - 5):
                            df.loc[row, 'price'] = df['price'][row - i]
                        i += 1

            # Dodamo symbol_id in preuredimo stolpce
            df['symbol_id'] = [symbol_id] * len(df.index)
            df = df[['symbol_id', 'date', 'price']]
            return df
        
        else:
            return stock


    def assets_on_day(self, user_id: int, symbol_id: str) -> pd.DataFrame:
        ''' Vrne df, v katerem je vrednost naše naložbe za vsak dan '''
        price_df = Graf().fix_stocks(symbol_id)
        trade_df = Graf().pripravi_trade_data(user_id, symbol_id)
        price_df['amount'] = [0] * len(price_df.index)
        price_df = price_df.sort_values(by='date').reset_index(drop=True)

        for row in price_df.index:
                same_amount = True
                for item in trade_df.index:
                    if price_df['date'][row] == trade_df['date'][item]:
                        same_amount = False
                        try:
                            price_df.loc[row, 'amount'] =  price_df['amount'][row-1] + trade_df['pnl'][item]
                        except KeyError:
                            price_df.loc[row, 'amount'] += trade_df['pnl'][item]
                    elif (price_df['date'][row] != trade_df['date'][item]) and (same_amount == True):
                        same_amount = False
                        try:
                            if row != 0:
                                price_df.loc[row, 'amount'] = price_df['amount'][row-1]
                            else:
                                price_df.loc[row, 'amount'] = 0
                        except KeyError:
                            price_df.loc[row, 'amount'] = 0

        price_df['value'] = price_df['price'] * price_df['amount']
        return price_df


    def usd_case(self, user_id: int) -> pd.DataFrame:
        ''' Simbol USD je obravnavan drugače, ker imajo lahko tradi
            v drugih assetih dobiček v USD '''
        df = Graf().datumi()
        trade_df = Graf().get_usd_data(user_id)
        df.rename(columns = {'price':'value'}, inplace = True)

        for row in df.index:
                same_amount = True
                for trade in trade_df.index:
                    if df['date'][row] == trade_df['date'][trade]:
                        same_amount = False
                        try:
                            df.loc[row, 'value'] =  df['value'][row-1] + trade_df['price'][trade]
                        except KeyError:
                            df.loc[row, 'value'] += trade_df['price'][trade]
                    elif (df['date'][row] != trade_df['date'][trade]) and (same_amount == True):
                        same_amount = False
                        try:
                            df.loc[row, 'value'] = df['value'][row-1]
                        except KeyError:
                            df.loc[row, 'value'] = 0
        return df


    def get_usd_data(self, user_id: int) -> pd.DataFrame:
        ''' Pomožna funkcija, ki vrne vse dobičke odražene v $ '''
        df = Graf().datumi()
        trade_1 = Graf().pripravi_trade_data(user_id, 'dollar', True)
        trade_2 = Graf().pripravi_trade_data(user_id, 'USD', True)
        trade_3 = Graf().pripravi_trade_data(user_id, 'USD', False)

        seznam = list()
        seznam.append(trade_1)
        seznam.append(trade_2)
        seznam.append(trade_3)

        trade_df = pd.concat(seznam, copy=False)
        trade_df = trade_df.groupby('date', as_index=False).sum()
        trade_df = trade_df.sort_values(by='date').reset_index(drop=True)

        # Vstavi ceno 0 za dni, ki niso definirani
        for row in df.index:
            for i in trade_df.index:
                if df['date'][row] == trade_df['date'][i]:
                    df.loc[row, 'price'] = trade_df['pnl'][i]
        return df


    def multy_asset(self, s_list: List[str], user_id: int) -> pd.DataFrame:
        ''' Sprejme seznam simbolov, za katere združi podatke
            za vsak dan '''
        seznam = list()
        df = pd.DataFrame([(0, 0), (0, 0)], columns=['date', 'value'])

        for simbol in s_list:
            if simbol == 'USD':
                s = Graf().usd_case(user_id)
            else:
                s = Graf().assets_on_day(user_id, simbol)
                s = s.drop(['symbol_id', 'price', 'amount'], axis=1)
            seznam.append(s)

        try:
            df = pd.concat(seznam, copy=False)
            df = df.groupby('date', as_index=False).sum()
            df = df.sort_values(by='date').reset_index(drop=True)
        except ValueError:
            pass
        return df


    def graph_html(self, user_id: int, symbol_list: List[str], X_column='date', Y_column='value'):
        ''' Ustvari in shrani graf kot assets.html '''
        data = Graf().multy_asset(symbol_list, user_id)
        #data = data.iloc[::5, :]
        fig = px.line(data, x='date', y='value',
                      labels=dict(date='čas', value='vrednost [$]'),
                      title='Vrednost naložbe')
        fig.write_html('views/graphs/assets.html')


    def graph_cake(self, user_id: int):
        ''' Ustavi in shrani tortni graf cake.html '''
        seznam = list()
        zacasni = list()
        asset_data = pd.read_sql(
                '''SELECT symbol_id
                FROM asset 
                WHERE user_id  = {}
            '''.format(user_id), conn
            )

        for row in asset_data.index:
            seznam.append(asset_data['symbol_id'][row])
        for simbol in seznam:
            if simbol != 'USD':
                df = Graf().assets_on_day(user_id, simbol)
            if simbol == 'USD':
                df = Graf().usd_case(user_id)
                df['symbol_id'] = ['USD'] * len(df.index)
            df = df.iloc[[-1]]
            zacasni.append(df)

        try:
            df = pd.concat(zacasni, copy=False)
            df = df.rename(columns={'symbol_id': 'simbol', 'value': 'vrednost'})
        except ValueError:
            df = pd.DataFrame([(0, 0), (0, 0)], columns=['vrednost', 'simbol'])
            
        fig = px.pie(df, values='vrednost', names='simbol',
                    color_discrete_sequence=px.colors.sequential.Purp_r, 
                    title='Celotni portfolio: ' + str(date.today()))
        fig.write_html('views/graphs/cake.html')



    ##################################################
    ############         STATISTIKA       ############
    ##################################################

    def win_rate(self, df: pd.DataFrame, strategy: str):
        ''' Pripravi win_rate.html in win_by_type.html grafa '''
        ''' Win_rate: '''
        rate = df['tp'].value_counts(normalize=True)
        try:
            l  = round(rate[0], 2)
        except KeyError:
            l = 0
        d1 = {  'wr': [1 - l, l],
                'value': ['Win', 'Loss']}
        data = pd.DataFrame(data=d1)
        fig = px.pie(data, values='wr', names='value', color='value',
                     color_discrete_map={'Win':'darkseagreen', 'Loss':'darksalmon'},
                     title='Win rate strategije ' + strategy)
        fig.write_html('views/graphs/win_rate.html')

        ''' Pripravi win rate glede na tip L/S in označi št. dobljenih TPjev '''
        ''' Win_by_type: '''
        df_long = Graf().filter_by_row(df, 'type', ['L'])
        rate_long = df_long['tp'].value_counts()
        df_short = Graf().filter_by_row(df, 'type', ['S'])
        rate_short = df_short['tp'].value_counts()
        Graf().index_error_fix(rate_long, rate_short)

        d_2 = { 'type': ['Long', 'Long','Long', 'Short', 'Short', 'Short'],
                'TPs': [2, 1, 0, 2, 1, 0],
                'count': [rate_long[2], rate_long[1], rate_long[0], rate_short[2], rate_short[1], rate_short[0]]}
        data_2 = pd.DataFrame(data=d_2)
        fig = px.bar(data_2, x='count', y='type', color='TPs',
                    color_continuous_scale= ['darksalmon','darkseagreen', 'olivedrab'],
                    labels=dict(date='tip', value='število'),
                    title='Uspešnost strategije ' + strategy)
        fig.write_html('views/graphs/win_by_type.html')


    def index_error_fix(self, rate_long: int | None, rate_short: int | None):
        ''' Izogne se KeyError, če vrednost v df ne obstaja '''
        for i in [0, 1, 2]:
            try:
                rate_long[i]
            except KeyError:
                rate_long[i] = 0
        
        for i in [0, 1, 2]:
            try:
                rate_short[i]
            except KeyError:
                rate_short[i] = 0


    def string_stats(self, df: pd.DataFrame) -> Tuple[float, float, float, float , float, float, float]:
        ''' Izpiše tuple vrednosti, ki nas zanimajo za statistikko '''
        # Poprečna RR in target
        avg_RR = round(df.loc[:, 'rr'].mean(), 2)
        avg_tar = round(df.loc[:, 'target'].mean(), 2)
        # Povprečno trajanje
        dur_df = df.loc[:, 'duration']
        for item in dur_df.index:
            # Odstranimo h pri duration in spremenimo str -> numeric
            dur_df.at[item] = re.sub('h', '', dur_df[item])
        dur_df = pd.to_numeric(dur_df)
        avg_dur = round(dur_df.mean(), 2)

        ''' Avg in Max vrednosti upoštevajo le vrednosti z $,
            saj bi sicer potrebovali cene za vsak tenutek,
            ne le 1x v dnevu '''
        pnl_df = Graf().pnl_type(df, True)
        pnl_df = pnl_df.loc[:, 'pnl']
        # Največja zmaga in izguba
        max_w = pnl_df.max()
        if max_w < 0:
            max_w = 0
        max_l = pnl_df.min()
        if max_l > 0:
            max_l = 0
        # Povprečna zmaga in izguba
        pnl_df = pnl_df.groupby(pnl_df > 0).mean()
        try:
            avg_w = round(pnl_df[True], 2)
        except KeyError:
            avg_w = 0
        try:
            avg_l = round(pnl_df[False], 2)
        except KeyError:
            avg_l = 0
        return (avg_RR, avg_tar, avg_dur, avg_w, avg_l, max_w, max_l)


    def graph_pnl(self, df: pd.DataFrame, strategy: str):
        ''' Ustvari graf pnl_graph.html '''
        df = Graf().pnl_type(df, True)
        df1 = df[['date', 'pnl']]
        df1 = df1.sort_values(by=['date'])

        sum = 0
        for item in df1.index:
            sum += round(df1['pnl'][item], 2)    
            df1.loc[item, 'pnl'] = sum
        
        fig = px.line(df1, x='date', y='pnl', 
                      labels=dict(date='čas', value='pnl [$]'),
                      title='Zaslužek strategije ' + strategy)
        fig.write_html('views/graphs/pnl_graph.html')


    def graph_stats(self, user_id: int, strategy: str) -> Tuple[float, float, float, float , float, float, float]:
        ''' Glavna funkcija, ki izriše grafe in vrne vrednosti za statistiko '''
        stats_data = pd.read_sql('''
                        SELECT user_id, symbol_id, type, strategy, rr, target, date, duration, tp, pnl 
                        FROM trade 
                        WHERE type = 'L' OR type = 'S' 
                    ''', conn)
        stats_data = Graf().filter_by_row(stats_data, 'user_id', [user_id])
        
        if strategy == 'All':
            pass
        else:
            stats_data = Graf().filter_by_row(stats_data, 'strategy', [strategy])
        Graf().win_rate(stats_data, strategy)
        Graf().graph_pnl(stats_data, strategy)
        return Graf().string_stats(stats_data)


    ##################################################
    ############         ANALIZA          ############
    ##################################################

    def stats(self, df: pd.DataFrame, strategy: str) -> Tuple[float, float, float, float , float, float]:
        ''' Izpiše tuple vrednosti, ki nas zanimajo za analizo
            in pripravi graf win_rate_anl.html '''
        # Win rate
        rate = df['tp'].value_counts(normalize=True)
        try:
            w_rate = round(1 - rate[0], 2)
        except KeyError:
            w_rate = 100
        # Povprečna zmaga in izguba
        pnl_df = df.loc[:, 'pnl']
        pnl_df = pnl_df.groupby(pnl_df > 0).mean()
        try:
            avg_w = round(pnl_df[True], 2)
        except KeyError:
            avg_w = 0
        try:
            avg_l = round(pnl_df[False], 2)
        except KeyError:
            avg_l = 0
        # Povprečna RR in target
        avg_rr = round(df.loc[:, 'rr'].mean(), 2)
        avg_tar = round(df.loc[:, 'target'].mean(), 2)
        # Povprečno trajanje
        avg_dur = round(df.loc[:, 'duration'].mean(), 2)

        # Graf win_rate_anl
        d = {'wr': [w_rate, 1 - w_rate], 
            'value': ['Win', 'Loss']}
        data = pd.DataFrame(data=d)
        fig = px.pie(data, values='wr', names='value', color='value',
                    color_discrete_map={'Win':'darkseagreen', 'Loss':'darksalmon'},
                    title='Uspešnost strategije ' + strategy)
        fig.write_html('views/graphs/win_rate_anl.html')

        # Pripavi 3d graf v pnl_3d.html
        fig = px.scatter_3d(df, x='target', y='rr', z='pnl',
              color = 'type',
              color_discrete_map = {'L':'darkseagreen', 'S':'darksalmon'},
              title = 'Profitabilnost strategije ' + strategy)
        fig.write_html('views/graphs/pnl_3d.html')
        return (w_rate, avg_w, avg_l, avg_rr, avg_tar, avg_dur)


    def analyze(self, user_id: int, strategy: str, duration: int, rr: int, target: int, tip: str) -> Tuple[float, float, float, float, float, float]:
        ''' Pripravi podatke za analizo, glede na dane parametre '''
        df = pd.read_sql('''
                SELECT user_id, symbol_id, type, strategy, rr, target, date, duration, tp, pnl 
                FROM trade 
                WHERE type = 'L' OR type = 'S'
            ''', conn)
        df = Graf().filter_by_row(df, 'user_id', [user_id])
        df = Graf().filter_by_row(df, 'strategy', [strategy])
        df = Graf().pnl_type(df, True)

        for item in df.index:
            df.loc[item, 'duration'] = re.sub('h', '', df['duration'][item])
        df['duration'] = pd.to_numeric(df['duration'])
        df = df[df['duration'] <= duration]

        df = df[df['rr'] <= rr]
        df = df[df['target'] <= target]
        df = df.reset_index()

        if tip == 'Oba':
            pass
        else:
            df = Graf().filter_by_row(df, 'type', [tip])
        return Graf().stats(df, strategy)
