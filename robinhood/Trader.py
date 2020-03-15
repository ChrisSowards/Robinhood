import warnings
from six.moves.urllib.request import getproxies
from six.moves import input

import getpass
import requests
import uuid
import pickle

from . import endpoints
from .enums import Transaction, Bounds


class Trader:
    """Wrapper class for fetching/parsing robinhood endpoints """
    session = None
    headers = None
    auth_token = None
    refresh_token = None
    current_device_token = None

    client_id = "c82SH0WZOsabOXGP2sxqcj34FxkvfnWRZBKlBjFS"

    ###########################################################################
    #                       Logging in and initializing
    ###########################################################################

    def __init__(self):
        self.session = requests.session()
        self.session.proxies = getproxies()
        self.headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "en;q=1, fr;q=0.9, de;q=0.8, ja;q=0.7, nl;q=0.6, it;q=0.5",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "X-robinhood-API-Version": "1.265.0",
            "Connection": "keep-alive",
            "User-Agent": "robinhood/823 (iPhone; iOS 7.1.2; Scale/2.00)"
        }
        self.session.headers = self.headers
        self.history = []

    def login(self, username=None, password=None, mfa_code=None, device_token=None):
        """Save and test login info for robinhood accounts

        Args:
            username (str): username
            password (str): password

        Returns:
            (bool): received valid auth token

        """
        if not username: username = input("Username: ")
        if not password: password = getpass.getpass()

        if not device_token:
            if self.current_device_token:
                device_token = self.current_device_token
            else:
                device_token = uuid.uuid1()
                self.current_device_token = device_token

        payload = {
            'username': username,
            'password': password,
            'grant_type': 'password',
            'device_token': device_token.hex,
            "token_type": "Bearer",
            'expires_in': 603995,
            "scope": "internal",
            'client_id': self.client_id,

        }

        if mfa_code:
            payload['access_token'] = self.auth_token
            payload['mfa_code'] = mfa_code
        else:
            payload['challenge_type'] = 'sms'

        try:
            res = self.session.post(endpoints.login(), data=payload, timeout=15, verify=True)
            res.raise_for_status()
            data = res.json()
            self.history.append(res)
        except requests.exceptions.HTTPError:
            raise Exception("login error")

        if 'mfa_required' in data.keys():
            mfa_code = input("MFA: ")
            return self.login(username, password, mfa_code, device_token)

        if 'access_token' in data.keys() and 'refresh_token' in data.keys():
            self.auth_token = data['access_token']
            self.refresh_token = data['refresh_token']
            self.headers['Authorization'] = 'Bearer ' + self.auth_token
            return res

        return False

    def logout(self):
        """Logout from robinhood

        Returns:
            (:obj:`requests.request`) result from logout endpoint

        """

        try:
            payload = {
                'client_id': self.client_id,
                'token': self.refresh_token
            }
            req = self.session.post(endpoints.logout(), data=payload, timeout=15)
            req.raise_for_status()
        except requests.exceptions.HTTPError as err_msg:
            warnings.warn('Failed to log out ' + repr(err_msg))

        self.headers['Authorization'] = None
        self.auth_token = None

        return req

    def is_logged_in(self):
        return "Authorization" in self.headers

    def _assert_logged_in(self):
        if not self.is_logged_in():
            raise Exception("Login required for caller")

    def _req_get(self, *args, timeout=15, **kwargs):
        res = self.session.get(*args, timeout=timeout, **kwargs)
        res.raise_for_status()
        return res

    def _req_get_json(self, *args, timeout=15, **kwargs):
        return self._req_get(*args, timeout=timeout, **kwargs).json()

    ###########################################################################
    #                        SAVING AND LOADING SESSIONS
    ###########################################################################

    def save_session(self, session_name):
        with open(session_name + '.rb', 'wb') as file:
            pickle.dump(self, file)

    @staticmethod
    def load_session(session_name):
        with open(session_name + '.rb', 'rb') as file:
            return pickle.load(file)

    ###########################################################################
    #                               GET DATA
    ###########################################################################

    def instrument(self, symbol):
        """Fetch instrument info

            Args:
                id (str): instrument id

            Returns:
                (:obj:`dict`): JSON dict of instrument
        """
        url = str(endpoints.instruments()) + "?symbol=" + str(symbol)
        return self._req_get_json(url)['results'][0]

    def quote(self, stock):
        """Fetch stock quote

            Args:
                stock (str): stock ticker

            Returns:
                (:obj:`dict`): JSON contents from `quotes` endpoint
        """
        stock = stock if isinstance(stock, list) else [stock]
        url = str(endpoints.quotes()) + "?symbols=" + ",".join(stock)
        return self._req_get(url).json()

    def historical_quotes(self, stock, interval, span, bounds=Bounds.REGULAR):
        """Fetch historical data for stock

            Note: valid interval/span configs
                interval = 5minute | 10minute + span = day, week
                interval = day + span = year
                interval = week
                TODO: NEEDS TESTS

            Args:
                stock (str): stock ticker
                interval (str): resolution of data
                span (str): length of data
                bounds (:enum:`Bounds`, optional): 'extended' or 'regular' trading hours

            Returns:
                (:obj:`dict`) values returned from `historicals` endpoint
        """
        stock = stock if isinstance(stock, list) else [stock]
        bounds = Bounds(bounds) if isinstance(bounds, str) else bounds

        url = endpoints.historicals()
        params = {
            'symbols': ','.join(stock).upper(),
            'interval': interval,
            'span': span,
            'bounds': bounds.name.lower()
        }
        url += '?' + '&'.join([f'{k}={v}' for k,v in params.items() if v])
        return self._req_get_json(url)['results'][0]

    def account(self):
        self._assert_logged_in()
        return self._req_get_json(endpoints.accounts())['result'][0]

    def fundamentals(self, stock):
        return self._req_get_json(endpoints.fundamentals(stock.upper()))

    def portfolios(self):
        """Returns the user's portfolio data """
        return self._req_get_json(endpoints.portfolios())['results'][0]

    def order_history(self):
        return self._req_get_json(endpoints.orders())

    def dividends(self):
        return self._req_get_json(endpoints.orders())

    ###########################################################################
    #                               PLACE ORDER
    ###########################################################################

    def place_market_buy_order(self, symbol, quantity, time_in_force=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                quantity (int): Number of shares to buy

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='market',
                                  trigger='immediate',
                                  side='buy',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  quantity=quantity))

    def place_limit_buy_order(self, symbol, quantity, price, time_in_force=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                price (float): The max price you're willing to pay per share
                quantity (int): Number of shares to buy

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='limit',
                                  trigger='immediate',
                                  side='buy',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  price=price,
                                  quantity=quantity))

    def place_stop_loss_buy_order(self, symbol, quantity, price, time_in_force=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                stop_price (float): The price at which this becomes a market order
                quantity (int): Number of shares to buy

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='market',
                                  trigger='stop',
                                  side='buy',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  stop_price=price,
                                  quantity=quantity))

    def place_stop_limit_buy_order(
            self, symbol, quantity, price, stop_price, time_in_force=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                stop_price (float): The price at which this becomes a limit order
                price (float): The max price you're willing to pay per share
                quantity (int): Number of shares to buy

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='limit',
                                  trigger='stop',
                                  side='buy',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  stop_price=stop_price,
                                  price=price,
                                  quantity=quantity))

    def place_market_sell_order(self, symbol, quantity, time_in_force=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                quantity (int): Number of shares to sell

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='market',
                                  trigger='immediate',
                                  side='sell',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  quantity=quantity))

    def place_limit_sell_order(self,
                               symbol=None,
                               time_in_force=None,
                               price=None,
                               quantity=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                price (float): The minimum price you're willing to get per share
                quantity (int): Number of shares to sell

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='limit',
                                  trigger='immediate',
                                  side='sell',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  price=price,
                                  quantity=quantity))

    def place_stop_loss_sell_order(self,
                                   symbol=None,
                                   time_in_force=None,
                                   stop_price=None,
                                   quantity=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                stop_price (float): The price at which this becomes a market order
                quantity (int): Number of shares to sell

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='market',
                                  trigger='stop',
                                  side='sell',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  stop_price=stop_price,
                                  quantity=quantity))

    def place_stop_limit_sell_order(
            self, symbol, quantity, price, stop_price, time_in_force=None):
        """Args:
                symbol (str): The ticker symbol of the instrument
                time_in_force (str): 'GFD' or 'GTC' (day or until cancelled)
                stop_price (float): The price at which this becomes a limit order
                price (float): The max price you're willing to get per share
                quantity (int): Number of shares to sell

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        return(self._submit_order(order_type='limit',
                                  trigger='stop',
                                  side='sell',
                                  symbol=symbol,
                                  time_in_force=time_in_force,
                                  stop_price=stop_price,
                                  price=price,
                                  quantity=quantity))

    def _submit_order(self,
                      symbol,
                      order_type=None,
                      time_in_force=None,
                      trigger=None,
                      price=None,
                      stop_price=None,
                      quantity=None,
                      side=None):
        """Submits order to robinhood helper method of:
                place_market_buy_order()
                place_limit_buy_order()
                place_stop_loss_buy_order()
                place_stop_limit_buy_order()
                place_market_sell_order()
                place_limit_sell_order()
                place_stop_loss_sell_order()
                place_stop_limit_sell_order()

            Args:
                instrument_URL (str): the RH URL for the instrument
                symbol (str): the ticker symbol for the instrument
                order_type (str): 'MARKET' or 'LIMIT'
                time_in_force (:enum:`TIME_IN_FORCE`): GFD or GTC (day or
                                                       until cancelled)
                trigger (str): IMMEDIATE or STOP enum
                price (float): The share price you'll accept
                stop_price (float): The price at which the order becomes a
                                    market or limit order
                quantity (int): The number of shares to buy/sell
                side (str): BUY or sell

            Returns:
                (:obj:`requests.request`): result from `orders` put command
        """
        self._assert_logged_in()
        # Used for default price input
        # Price is required, so we use the current bid price if it is not specified
        current_quote = self.quote(symbol)
        current_bid_price = current_quote['bid_price']

        # Start with some parameter checks. I'm paranoid about $.
        instrument_URL = None
        if symbol is None:
            raise(ValueError('Neither instrument_URL nor symbol were passed to submit_order'))
        for result in self.instrument(symbol):
            if result['symbol'].upper() == symbol.upper():
                instrument_URL = result['url']
                break
        if instrument_URL is None:
            raise(ValueError('instrument_URL could not be defined. Symbol %s not found' % symbol))

        if symbol is None:
            symbol = self.session.get(instrument_URL, timeout=15).json()['symbol']

        if side is None:
            raise(ValueError('Order is neither buy nor sell in call to submit_order'))

        if order_type is None and price is None:
            if stop_price is None:
                order_type = 'market'
            else:
                order_type = 'limit'

        symbol = str(symbol).upper()
        order_type = str(order_type).lower()
        time_in_force = str(time_in_force).lower()
        trigger = str(trigger).lower()
        side = str(side).lower()

        if (order_type != 'market') and (order_type != 'limit'):
            raise(ValueError('Invalid order_type in call to submit_order'))

        if order_type == 'limit':
            if price is None:
                raise(ValueError('Limit order has no price in call to submit_order'))
            if price <= 0:
                raise(ValueError('Price must be positive number in call to submit_order'))

        if trigger == 'stop':
            if stop_price is None:
                raise(ValueError('Stop order has no stop_price in call to submit_order'))
            if stop_price <= 0:
                raise(ValueError('Stop_price must be positive number in call to submit_order'))

        if stop_price is not None:
            if trigger != 'stop':
                raise(ValueError('Stop price set for non-stop order in call to submit_order'))

        if price is None:
            if order_type == 'limit':
                raise(ValueError('Limit order has no price in call to submit_order'))

        if price is not None:
            if order_type.lower() == 'market':
                raise(ValueError('Market order has price limit in call to submit_order'))
            price = float(price)
        else:
            price = current_bid_price # default to current bid price

        if quantity is None:
            raise(ValueError('No quantity specified in call to submit_order'))

        quantity = int(quantity)

        if quantity <= 0:
            raise(ValueError('Quantity must be positive number in call to submit_order'))

        payload = {}

        for field, value in [
                ('account', self.get_account()['url']),
                ('instrument', instrument_URL),
                ('symbol', symbol),
                ('type', order_type),
                ('time_in_force', time_in_force),
                ('trigger', trigger),
                ('price', price),
                ('stop_price', stop_price),
                ('quantity', quantity),
                ('side', side)
            ]:
            if(value is not None):
                payload[field] = value

        print(payload)
        res = self.session.post(endpoints.orders(), data=payload, timeout=15)
        res.raise_for_status()

        return res

    def cancel_order(self, order_id):
        """
        Cancels specified order and returns the response (results from `orders` command).
        If order cannot be cancelled, `None` is returned.
        Args:
            order_id (str or dict): Order ID string that is to be cancelled or open order dict returned from
            order get.
        Returns:
            (:obj:`requests.request`): result from `orders` put command
        """
        if isinstance(order_id, str):
            try:
                order = self.session.get(endpoints.orders() + order_id, timeout=15).json()
            except (requests.exceptions.HTTPError) as err_msg:
                raise ValueError('Failed to get Order for ID: ' + order_id + '\n Error message: ' + repr(err_msg))

            if order.get('cancel') is not None:
                try:
                    res = self.session.post(order['cancel'], timeout=15)
                    res.raise_for_status()
                    return res
                except (requests.exceptions.HTTPError) as err_msg:
                    raise ValueError('Failed to cancel order ID: ' + order_id + '\n Error message: '+ repr(err_msg))
                    return None

        if isinstance(order_id, dict):
            order_id = order_id['id']
            try:
                order = self.session.get(endpoints.orders() + order_id, timeout=15).json()
            except (requests.exceptions.HTTPError) as err_msg:
                raise ValueError('Failed to get Order for ID: ' + order_id
                    + '\n Error message: '+ repr(err_msg))

            if order.get('cancel') is not None:
                try:
                    res = self.session.post(order['cancel'], timeout=15)
                    res.raise_for_status()
                    return res
                except (requests.exceptions.HTTPError) as err_msg:
                    raise ValueError('Failed to cancel order ID: ' + order_id
                         + '\n Error message: '+ repr(err_msg))
                    return None

        elif not isinstance(order_id, str) or not isinstance(order_id, dict):
            raise ValueError('Cancelling orders requires a valid order_id string or open order dictionary')


        # Order type cannot be cancelled without a valid cancel link
        else:
            raise ValueError('Unable to cancel order ID: ' + order_id)
