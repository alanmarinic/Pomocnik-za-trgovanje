import os
import re

from datetime import date
from functools import wraps

from bottleext import get, post, run, request, template, redirect, static_file, url, response, TEMPLATES

import psycopg2, psycopg2.extensions, psycopg2.extras
psycopg2.extensions.register_type(psycopg2.extensions.UNICODE)

from auth_public import *
from Podatki import get_history as gh
from graphs import Graf

from Database import Repo
from modeli import *
from Services import AuthService


repo = Repo()
auth = AuthService(repo)
graf = Graf()

# Privzete nastavitve
SERVER_PORT = os.environ.get('BOTTLE_PORT', 8080)
RELOADER = os.environ.get('BOTTLE_RELOADER', True)


# Priklop na bazo
# conn = psycopg2.connect(database=db, host=host, user=user, password=password, port=DB_PORT)
# cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) 


@get('/static/<filename:path>')
def static(filename):
   return static_file(filename, root='static')

def cookie_required(f):
    ''' Dekorator, ki zahteva veljaven piškotek '''
    @wraps(f)
    def decorated( *args, **kwargs): 
        cookie = request.get_cookie('uporabnik')
        if cookie:
            return f(*args, **kwargs)
        return template('prijava.html', 
                        uspesna_prijava=False, 
                        sporocilo='Potrebna je prijava',
                        naslov='Pomočnik za trgovanje')
    return decorated

@get('/graphs/<ime>.html')
def graf_assets(ime: str):
    return template(f'graphs/{ime}.html')


#############################################################
#############      PRIJAVA IN REGISTRACIJA      #############
#############################################################

@get('/')
def zacetna_stran():
    return template('prijava.html', 
                    uspesna_prijava=True, 
                    sporocilo='',
                    naslov='Pomočnik za trgovanje')

@post('/prijava')
def prijava_post():
    uporabnisko_ime = request.forms.ime
    geslo = request.forms.geslo

    if not auth.obstaja_uporabnik(uporabnisko_ime):
        return template('prijava.html', 
                        uspesna_prijava=False, 
                        sporocilo='Uporabnik s tem imenom ne obstaja',
                        naslov='Pomočnik za trgovanje')

    prijava = auth.prijavi_uporabnika(uporabnisko_ime, geslo)
    if prijava[0] == 0:
        return template('prijava.html',
                        uspesna_prijava=False, 
                        sporocilo='Napačno uporabinško ime ali geslo!',
                        naslov='Pomočnik za trgovanje')
    
    # Nastavi piškotek
    response.set_cookie('uporabnik', uporabnisko_ime)

    user_id = repo.dobi_gen_id(app_user, uporabnisko_ime, 'user_name')[0]
    redirect(url('index', id=user_id))

@get('/odjava')
def logout():
    response.delete_cookie('uporabnik')
    return template('prijava.html', 
                        uspesna_prijava=False, 
                        sporocilo='Odjava uspešna',
                        naslov='Pomočnik za trgovanje')

#############################################################

@get('/registracija')
def registracija():
    return template('registracija.html', 
                    uspesna_registracija=True, 
                    sporocilo='',
                    naslov='Registracija')

@post('/registracija')
def registracija_post():
    ime = request.forms.name
    priimek = request.forms.surname
    datum_rojstva = request.forms.date_of_birth
    uporabnisko_ime = request.forms.user_name
    geslo = request.forms.password

    if auth.obstaja_uporabnik(uporabnisko_ime):
        return template('registracija.html', 
                        uspesna_registracija=False, 
                        sporocilo='Registracija ni možna, to uporabniško ime že obstaja.',
                        naslov='Registracija')

    auth.dodaj_uporabnika(ime, priimek, datum_rojstva, uporabnisko_ime, geslo)
    return template('prijava.html',  
                    uspesna_prijava=False,
                    sporocilo='Registracija uspešna!',
                    naslov='Pomočnik za trgovanje')    

#############################################################

@get('/<id>/index')
@cookie_required
def index(id: int):
    cookie = request.get_cookie('uporabnik')
    user_seznam = repo.dobi_gen_id(app_user, cookie, 'user_name')
    user_id = user_seznam[0]
    user_ime = user_seznam[1]

    # V bazi posodobi price_history
    df = gh.update_price_history()
    repo.posodobi_price_history(df)
    return template('index.html', user_ime=user_ime , user_id=user_id)

#############################################################

@get('/<id>/uredi_profil')
@cookie_required
def uredi_profil(id: int):
    seznam = repo.get_user(id)
    return template('uredi_profil.html', 
                    sprememba=False, 
                    podatki=seznam, 
                    sporocilo='',
                    user_id=id,
                    naslov='Uredi profil')   

@post('/posodobi')
def posodobi():
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    ime = request.forms.ime
    priimek = request.forms.priimek
    datum = request.forms.datum
    geslo = request.forms.geslo
    repo.posodobi_user(user_id, ime, priimek, datum, geslo)

    seznam = repo.get_user(user_id)
    return template('uredi_profil.html', 
                    sprememba=True, 
                    podatki=seznam, 
                    sporocilo='Sprememba uspešna!',
                    user_id=user_id,
                    naslov='Uredi profil') 


#############################################################
##############             NALOŽBE             ##############
#############################################################

@get('/<id>/pregled_nalozb')
@cookie_required
def dodaj(id: int):
    seznam = repo.dobi_pare()
    return template('pregled_nalozb.html', 
                    pravilen_simbol=True, 
                    pairs=seznam, 
                    sporocilo='',
                    user_id=id,
                    naslov='Dodaj naložbo')

@post('/dodaj_par')
def dodaj_par():
    ''' Doda nov par v tabelo pari '''
    symbol = request.forms.symbol
    symbol = symbol.upper()
    name = request.forms.ime

    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    seznam = repo.dobi_pare()
    # Preveri ali vnešen simbol obstaja
    if gh.preveri_ustreznost(f'{symbol}') == 0:
        return template('pregled_nalozb.html', 
                        pravilen_simbol=False,
                        pairs=seznam,
                        sporocilo='Vnešen napačen simbol',
                        user_id=user_id,
                        naslov='Dodaj naložbo')

    
    if repo.dodaj_par(symbol, name) == 1:
        # Vnese simbol v tabelo par
        gh.get_historic_data(['{}'.format(symbol)], date.today())
        repo.uvozi_Price_History('{}.csv'.format(symbol))
        gh.merge_csv(gh.get_symbols(), 'price_history.csv')
        return template('pregled_nalozb.html', 
                        pravilen_simbol=True, 
                        pairs=seznam,
                        sporocilo='Simbol uspešno dodan', 
                        user_id=user_id,
                        naslov='Dodaj naložbo')
    else:
        return template('pregled_nalozb.html', 
                        pravilen_simbol=False, 
                        pairs=seznam,
                        sporocilo='Simbol je že v bazi', 
                        user_id=user_id,
                        naslov='Dodaj naložbo')

#############################################################

@get('/<id>/nalozbe')
@cookie_required
def nalozbe(id: int):
    ''' Namesto id iz funkcije uporabi cookie zato, da če uporabnik
    ročno spremeni url, ne vidi podatkov ostalih uporabnik! '''
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    seznam = repo.dobi_asset_amount_by_user(user_id)

    return template('nalozbe.html',
                    assets=seznam, 
                    napaka=False, 
                    sporocilo='', 
                    user_id=id, 
                    naslov='Asset')

@post('/buy_sell')
def buy_sell():
    ''' Če kupimo ali prodamo naložbo, ta funkcija
        vnese spremembe v tabelo assets in doda trade '''
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    symbol = request.forms.symbol
    datum = request.forms.datum
    tip = request.forms.tip
    amount = float(repo.sign(request.forms.amount, tip))

    try:
        # Preveri da smo vnesli pravilen simbol
        if repo.dobi_gen_id(pair, symbol, id_col='symbol'):
            pass
    except Exception:
        seznam = repo.dobi_asset_amount_by_user(user_id)
        return template('nalozbe.html', 
                        assets=seznam, 
                        napaka=True, 
                        sporocilo='Napačen simbol!',
                        user_id=user_id, 
                        naslov='Asset')

    # Zabeleži trade v tabelo trades
    trejd = trade(  user_id = user_id,
                    symbol_id = symbol, 
                    type = tip,
                    date = datum, 
                    pnl = amount
                )
    repo.dodaj_gen(trejd, serial_col='id_trade')

    # Vnese spremembo v tabelo assets
    repo.trade_result(user_id, symbol, amount)
    seznam = repo.dobi_asset_amount_by_user(user_id)
    return template('nalozbe.html', 
                    assets=seznam, 
                    napaka=False, 
                    sporocilo='Transakcija potrjena',
                    user_id=user_id,
                    naslov='Asset')


#############################################################

@get('/<id>/napredek')
@cookie_required
def performance(id: int):
    ''' Namesto id iz funkcije uporabi cookie zato, da če uporabnik
    ročno spremeni url, ne vidi podatkov ostalih uporabnik! '''
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    user_assets = repo.dobi_asset_by_user(user_id)

    graf.graph_html(user_id, user_assets) 
    graf.graph_cake(user_id)
    TEMPLATES.clear()
    return template('performance.html', assets=user_assets, user_id=id, naslov='Poglej napredek')

@post('/new_equity_graph')
def new_equity_graph():
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    user_assets = repo.dobi_asset_by_user(user_id)

    simboli_graf = request.forms.simboli
    seznam = re.split(r' ', simboli_graf
                      )
    graf.graph_html(user_id, seznam)
    TEMPLATES.clear()
    return template('performance.html', assets=user_assets, user_id=user_id, naslov='Poglej napredek')


#############################################################
#################         TRADES            #################
#############################################################

@get('/<id>/trades')
@cookie_required
def trades(id: int):
    ''' Namesto id iz funkcije uporabi cookie zato, da če uporabnik
    ročno spremeni url, ne vidi podatkov ostalih uporabnik! '''
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    seznam = repo.dobi_trade_delno(user_id)
    return template('trades.html', trade=seznam, sporocilo='', user_id=id, naslov='Dodaj trade')

@post('/dodaj_trade')
def dodaj_trade():
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    simbol = request.forms.symbol
    TP = request.forms.TP
    PNL = request.forms.PNL

    try: # Preveri ali vnešen simbol obstaja
        if repo.dobi_gen_id(pair, simbol, id_col='symbol'):
            if TP == '':
                TP = psycopg2.extensions.AsIs('NULL')
            trejd = trade(  user_id = user_id,
                            symbol_id = simbol, 
                            type = request.forms.type,
                            strategy = request.forms.strategy,
                            rr = request.forms.RR,
                            target = request.forms.target,
                            date = request.forms.date, 
                            duration = request.forms.duration,
                            tp = TP,
                            pnl = PNL
                        )
            # Zabeleži trade v tabelo trades
            repo.dodaj_gen(trejd, serial_col='id_trade')
            # Izid trada poračuna v asset
            repo.pnl_trade(user_id, simbol, PNL)

            seznam = repo.dobi_trade_delno(user_id)
            return template('trades.html',
                            trade=seznam, 
                            sporocilo='Trade dodan', 
                            user_id=user_id, 
                            naslov='Dodaj trade')
    except:
        seznam = repo.dobi_trade_delno(user_id)
        return template('trades.html', 
                        trade=seznam, 
                        sporocilo = '''Napačen simbol, če želite dodati 
                        trade za njega, ga najprej dodajte v tabelo pari!''',
                        user_id=user_id,
                        naslov='Dodaj trade')

@post('/<trade_id>/delete_trade')
def delete_trade(trade_id: int):
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    repo.izbrisi_trade(trade_id)
    seznam = repo.dobi_trade_delno(user_id)
    return template('trades.html', 
                    trade=seznam, 
                    sporocilo='Trade izbrisan!',
                    user_id=user_id, 
                    naslov='Dodaj trade')

@get('/<param>/uredi')
@cookie_required
def uredi(param: str):
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    seznam = repo.dobi_trade_delno(user_id, param)
    return template('trades.html', 
                    trade=seznam, 
                    sporocilo='', 
                    user_id=user_id, 
                    naslov='Dodaj trade')


#############################################################

@get('/<id>/statistika')
@cookie_required
def stats(id: int):
    ''' Namesto id iz funkcije uporabi cookie zato, da če uporabnik
    ročno spremeni url, ne vidi podatkov ostalih uporabnik! '''
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    seznam = repo.dobi_strategije(user_id)

    # Če uporabim samo id namesto user_id ne izračuna stats_tuple?
    stats_tuple = graf.graph_stats(user_id, 'All')
    TEMPLATES.clear()
    return template('stats.html', 
                    strategy=seznam, 
                    podatki=stats_tuple, 
                    user_id=id, 
                    izbrana='',
                    sporocilo='',
                    naslov='Statistika')

@post('/strategy')
def strategy():
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    strategy = request.forms.strategy
    seznam = repo.dobi_strategije(user_id)
    stats_tuple = graf.graph_stats(user_id, strategy)
    TEMPLATES.clear()
    if strategy == '':
        return template('stats.html', 
                    strategy=seznam, 
                    podatki=stats_tuple, 
                    user_id=user_id,
                    izbrana=strategy,
                    sporocilo='Izberi natanko eno strategijo!',
                    naslov='Statistika')

    return template('stats.html', 
                    strategy=seznam, 
                    podatki=stats_tuple, 
                    user_id=user_id,
                    izbrana=strategy,
                    sporocilo='',
                    naslov='Statistika')

#############################################################

@get('/<id>/analiza')
@cookie_required
def analyze_main(id: int):
    ''' Namesto id iz funkcije uporabi cookie zato, da če uporabnik
    ročno spremeni url, ne vidi podatkov ostalih uporabnik! '''
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]

    seznam = repo.dobi_strategije(user_id)
    return template('analysis.html', 
                    strategy=seznam, 
                    podatki=(0, 0, 0, 0, 0, 0), 
                    user_id=id,
                    izbrana='',
                    sporocilo='',
                    naslov='Analiza')

@post('/analyze')
def analyze_f():
    cookie = request.get_cookie('uporabnik')
    user_id = repo.dobi_gen_id(app_user, cookie, 'user_name')[0]
    strategy = request.forms.strategy
    analiza_stats = graf.analyze(   
        user_id, 
        strategy, 
        int(request.forms.duration), 
        int(request.forms.rr), 
        int(request.forms.target), 
        request.forms.tip
        )
    TEMPLATES.clear()
    seznam = repo.dobi_strategije(user_id)
    if strategy == '':
        return template('analysis.html',
                    strategy=seznam, 
                    podatki=analiza_stats, 
                    user_id=user_id,
                    izbrana=strategy,
                    sporocilo='Izberi natanko eno strategijo!',
                    naslov='Analiza')
    
    return template('analysis.html',
                    strategy=seznam, 
                    podatki=analiza_stats, 
                    user_id=user_id,
                    izbrana=strategy,
                    sporocilo='',
                    naslov='Analiza')

#############################################################

if __name__ == '__main__':
    run(host='localhost', port=SERVER_PORT, reloader=RELOADER)
