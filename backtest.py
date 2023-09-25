import numpy as np
import pandas as pd

import sys
import math
from abc import abstractmethod, ABCMeta

import talib

# =============================================================================

DEBUG = False

class Backtest:
    def __init__(self, datapath, strategy, capital, long_max=1, short_max=1):
        self.data = pd.read_csv(datapath)
        self.index = 0
        self.capital = capital
        self.strategy = strategy

        # Working
        self.quantity_held = 0
        self.quantity_owed = 0
        self.balance = capital
        self.pnl = 0
        self.equity = capital
        
        # Trades
        self.long_max = long_max
        self.short_max = short_max
        self.long_count = 0
        self.short_count = 0

        self.trades = [] # Active trades
        self.entered_positions = 0
        self.winning_positions = 0

        # Statistics
        self.equity_peak = capital
        self.history = [] # Trade history
        self.trade_duration = 0
        self.commission_total = 0

        # For trades not explicitly linked, assume a trade of some position (short/long)
        # is matches with the next opposite trade of the same position
        # - store previous position size
        self.previous_long = capital
        self.previous_short = capital
    
    def price(self):
        return self.data["Close"].iloc[self.index]
    
    def run(self):
        global DEBUG
        if len(sys.argv) == 2:
            if sys.argv[1] == "1":
                DEBUG = True

        while self.index < self.data.shape[0]:
            if DEBUG == True:
                input()

            i = 0
            while i < len(self.trades): # Execute queued trades
                if self.trades[i].execute() == True:
                    self.trades.remove(self.trades[i]) # Remove once executed
                    i -= 1
                i += 1
            
            # Strategies are executed immediately, otherwise are placed in the queue
            # for execution in future periods
            self.strategy(bt)

            # Calculate current equity
            self.equity = self.balance + (self.quantity_held * self.price()) - \
                (self.quantity_owed * self.price())
            if self.equity <= 0:
                print("No more equity remains.")
                return

            if DEBUG == True:
                print(f"{self.index} Close: " + str(self.price()))
                print("Held: " + str(self.quantity_held))
                print("Owed: " + str(self.quantity_owed))
                print("Balance: " + str(self.balance))
                print("Equity: " + str(self.equity))
            
            self.index += 1

            # Statistics
            if self.equity > self.equity_peak: # Peak Equity
                self.equity_peak = self.equity
            if self.long_count > 0 or self.short_count > 0: # Trade Duration
                self.trade_duration += 1

        # Liquidate all positions at the end
        self.index -= 1
        LONGSELL(bt, bt.quantity_held, commission=0).execute() # First do long positions
        SHORTBUY(bt, bt.quantity_owed, commission=0).execute()

        self.equity = self.balance + (self.quantity_held * self.price()) - \
                (self.quantity_owed * self.price()) # Recalculate

    def report(self):
        print("\n========================================")
        print("Start: {}".format(self.data["Date"].iloc[0]))
        print("End: {}".format(self.data["Date"].iloc[self.data.shape[0]-1]))
        print("Equity Final [$]: {:.2f}".format(self.equity))
        print("Equity Peak [$]: {:.2f}".format(self.equity_peak))
        print("Arithmetic Return [%]: {:.2f}".format(100*(self.equity - self.capital)/self.capital))
        print("Geometric Return [%]: {}".format("null"))
        print("Buy-and-hold Return [%]: {:.2f}".format(100*(self.price() - self.data["Close"].iloc[0])/self.data["Close"].iloc[0]))
        print("# Positions: {}".format(self.entered_positions))
        if self.entered_positions == 0:
            print("Win Rate [%]: null")
            print("Average Duration [t]: null")
        else:
            print("Win Rate [%]: {:.2f}".format(100*self.winning_positions/self.entered_positions))
            print("Average Duration [t]: {:.2f}".format(self.trade_duration/self.entered_positions))
        print("Commissions [$]: {:.2f}".format(self.commission_total))
        print("Average Commission / Position [$]: {:.2f}".format(self.commission_total/self.entered_positions))

# -----------------------------------------------------------------------------

class Order(metaclass=ABCMeta):
    def __init__(self, bt: Backtest, size: float, limit: float = None, 
        commission: float = 0, margin: float = 1):
        self.bt = bt
        self.size = size
        self.limit = limit
        self.commission = commission
        self.margin = margin
        self.leverage = 1/margin
    
    @abstractmethod
    def add(self):
        pass

    @abstractmethod
    def execute(self):
        pass
    
    @abstractmethod
    def valid(self):
        pass
 
class LONGBUY(Order):
    def __init__(self, bt: Backtest, size: float, limit: float = None, 
        commission: float = 0, margin: float = 1):
        super().__init__(bt, size, limit, commission, margin)
    
    def valid(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.bt.long_count >= self.bt.long_max:
            # print("Max number of long positions already held.")
            return False
        return True

    def add(self):
        if self.valid() == False:
            return False

        self.bt.long_count += 1

        # Execute Immediately
        if self.execute() == False:
            self.bt.trades.append(self)

        return True

    def execute(self):
        if self.size * self.bt.price() > self.bt.balance:
            # print("Insufficient balance to buy.")
            return False
        commission_amount = self.commission * self.size * self.bt.price()
        if self.size * self.bt.price() > self.bt.balance - commission_amount:
            print("Not enough balance to include commission payment.")
            return False
        
        # Consider Limit
        if self.limit != None:
            if self.bt.price() > self.limit:
                return False

        # Statistics
        self.bt.entered_positions += 1
        self.bt.history.append("LONG BUY: Q: {}, C: {}, B: {}, E: {}".format(self.size, self.bt.price(), self.bt.balance, self.bt.equity))

        self.bt.quantity_held += self.size
        self.bt.balance -= self.size * self.bt.price()
        self.bt.balance -= commission_amount
        self.bt.commission_total += commission_amount
        print("LONG BUY")

        # Save Trade
        self.bt.previous_long = self.size * self.bt.price()

        return True
    
class LONGSELL(Order):
    def __init__(self, bt: Backtest, size: float, limit: float = None, 
        commission: float = 0, margin: float = 1):
        super().__init__(bt, size, limit, commission, margin)
    
    def valid(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.size > self.bt.quantity_held:
            # print("Insufficient quantity held to sell.")
            return False
        return True

    def add(self):
        if self.valid() == False:
            return False

        # Execute Immediately
        if self.execute() == False:
            self.bt.trades.append(self)
        
        return True

    def execute(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.size > self.bt.quantity_held:
            # print("Attempting to sell more than held.")
            return False
        commission_amount = self.commission * self.size * self.bt.price()
        if commission_amount > self.bt.balance + self.size * self.bt.price():
            print("Not enough balance to include commission payment.")
            return False
        
        # Consider Limit
        if self.limit != None:
            if self.bt.price() < self.limit:
                return False

        # Statistics
        self.bt.long_count -= 1
        self.bt.history.append("LONG SELL: Q: {}, C: {}, B: {}, E: {}".format(self.size, self.bt.price(), self.bt.balance, self.bt.equity))

        self.bt.quantity_held -= self.size
        self.bt.balance += self.size * self.bt.price()
        self.bt.balance -= commission_amount
        self.bt.commission_total += commission_amount
        print("LONG SELL")

        # Winning Trades
        if self.size * self.bt.price() > self.bt.previous_long:
            self.bt.winning_positions += 1

        return True

class SHORTSELL(Order):
    def __init__(self, bt: Backtest, size: float, limit: float = None, 
        commission: float = 0, margin: float = 1):
        super().__init__(bt, size, limit, commission, margin)
    
    def valid(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.bt.short_count >= self.bt.short_max:
            # print("Max number of short positions already held.")
            return False
        return True

    def add(self):        
        if self.valid() == False:
            return False

        self.bt.short_count += 1

        # Execute Immediately
        if self.execute() == False:
            self.bt.trades.append(self)
        
        return True
    
    def execute(self):
        if self.size * self.bt.price() > self.bt.balance:
            # print("Insufficient balance held to conduct a short sell.")
            return False
        commission_amount = self.commission * self.size * self.bt.price()
        if self.size * self.bt.price() > self.bt.balance - commission_amount:
            print("Not enough balance to include commission payment.")
            return False

        # Consider Limit
        if self.limit != None:
            if self.bt.price() < self.limit:
                return False

        # Statistics
        self.bt.entered_positions += 1
        self.bt.history.append("SHORT SELL: Q: {}, C: {}, B: {}, E: {}".format(self.size, self.bt.price(), self.bt.balance, self.bt.equity))
        
        self.bt.quantity_owed += self.size
        self.bt.balance += self.size * self.bt.price()
        self.bt.balance -= commission_amount
        self.bt.commission_total += commission_amount
        print("SHORT SELL")

        # Save Trade
        self.bt.previous_short = self.size * self.bt.price()

        return True

class SHORTBUY(Order):
    def __init__(self, bt: Backtest, size: float, limit: float = None, 
        commission: float = 0, margin: float = 1):
        super().__init__(bt, size, limit, commission, margin)
    
    def valid(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.size > self.bt.quantity_owed:
            # print("Insufficient equity owed to buy back.")
            return False
        return True

    def add(self):
        if self.valid() == False:
            return False

        # Execute Immediately
        if self.execute() == False:
            self.bt.trades.append(self)
        
        return True
    
    def execute(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.size > self.bt.quantity_owed:
            # print("Attempting to buy back more than owed.")
            return False
        commission_amount = self.commission * self.size * self.bt.price()
        if commission_amount > self.bt.balance + self.size * self.bt.price():
            print("Not enough balance to include commission payment.")
            return False

        # Consider Limit
        if self.limit != None:
            if self.bt.price() > self.limit:
                return False

        # Statistics
        self.bt.short_count -= 1
        self.bt.history.append("SHORT BUY: Q: {}, C: {}, B: {}, E: {}".format(self.size, self.bt.price(), self.bt.balance, self.bt.equity))

        self.bt.quantity_owed -= self.size
        self.bt.balance -= self.size * self.bt.price()
        self.bt.balance -= commission_amount
        self.bt.commission_total += commission_amount
        print("SHORT BUY")

        # Winning Trades        
        if self.size * self.bt.price() < self.bt.previous_short:
            self.bt.winning_positions += 1

        return True

# Stop Loss for Long
class STOPSELL(Order): 
    def __init__(self, bt: Backtest, size: float, limit: float, 
        commission: float = 0, margin: float = 1):
        super().__init__(bt, size, limit, commission, margin)
    
    def valid(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.size > self.bt.quantity_held:
            # print("Insufficient quantity held to sell.")
            return False
        return True
    
    def add(self):
        if self.valid() == False:
            return False

        # Execute Immediately
        if self.execute() == False:
            self.bt.trades.append(self)
        
        return True

    def execute(self):
        if self.size > self.bt.quantity_held:
            # print("Attempting to sell more than held.")
            return False
        commission_amount = self.commission * self.size * self.bt.price()
        if commission_amount > self.bt.balance + self.size * self.bt.price():
            print("Not enough balance to include commission payment.")
            return False
        
        # Consider Long Stop Limit
        if self.bt.price() > self.limit:
            return False

        # Statistics
        self.bt.long_count -= 1
        self.bt.history.append("STOP SELL: Q: {}, C: {}, B: {}, E: {}".format(self.size, self.bt.price(), self.bt.balance, self.bt.equity))

        self.bt.quantity_held -= self.size
        self.bt.balance += self.size * self.bt.price()
        self.bt.balance -= commission_amount
        self.bt.commission_total += commission_amount
        print("STOP SELL")

        return True

# Stop Loss for Short
class STOPBUY(Order): 
    def __init__(self, bt: Backtest, size: float, limit: float, 
        commission: float = 0, margin: float = 1):
        super().__init__(bt, size, limit, commission, margin)
    
    def valid(self):
        if self.size <= 0:
            # print("Order size must be positive.")
            return False
        if self.size > self.bt.quantity_owed:
            # print("Insufficient equity owed to buy back.")
            return False
        return True

    def add(self):
        if self.valid() == False:
            return False

        # Execute Immediately
        if self.execute() == False:
            self.bt.trades.append(self)
        
        return True
    
    def execute(self):
        if self.size > self.bt.quantity_owed:
            # print("Attempting to buy back more than owed.")
            return False
        commission_amount = self.commission * self.size * self.bt.price()
        if commission_amount > self.bt.balance + self.size * self.bt.price():
            print("Not enough balance to include commission payment.")
            return False

        # Consider Stop Buy Limit
        if self.bt.price() < self.limit:
            return False

        # Statistics
        self.bt.short_count -= 1
        self.bt.history.append("STOP BUY: Q: {}, C: {}, B: {}, E: {}".format(self.size, self.bt.price(), self.bt.balance, self.bt.equity))

        self.bt.quantity_owed -= self.size
        self.bt.balance -= self.size * self.bt.price()
        self.bt.balance -= commission_amount
        self.bt.commission_total += commission_amount
        print("STOP BUY")

        return True

# One-Cancels-the-Other order pair.
class OCO:
    def __init__(self, bt: Backtest, order1, order2):
        self.bt = bt
        self.order1 = order1
        self.order2 = order2
    
    def add(self):
        if self.order1.valid() == False:
            return False
        if self.order2.valid() == False:
            return False
        
        print("Added OCO order.")
        self.bt.trades.append(self)
        return True

    def execute(self):
        if self.order1.execute():
            print("{} cancelled due to OCO.".format(type(self.order2)))
            return True
        if self.order2.execute():
            print("{} cancelled due to OCO.".format(type(self.order1)))
            return True
        return False

# =============================================================================
# Function Definitions

def RSI(bt):
    # For n periods, RSI requires at least n+1 data points.
    if bt.index < 15: 
        return
    
    nparray = bt.data["Close"].iloc[bt.index-15:bt.index].to_numpy()
    rsi = talib.RSI(nparray, 14)[-1]
    print("RSI: {:.2f}".format(rsi)) 
    if rsi > 70:
        # LONGSELL(bt, bt.quantity_held).add()
        # SHORTSELL(bt, math.floor(bt.balance/bt.price())).add()
        LONGSELL(bt, 1, commission=0.002).add()
        SHORTSELL(bt, 1, commission=0.002).add()

    if rsi < 30:
        SHORTBUY(bt, 1, commission=0.002).add()
        LONGBUY(bt, 1, commission=0.002).add()
        # SHORTBUY(bt, bt.quantity_owed).add()
        # LONGBUY(bt, math.floor(bt.balance/bt.price())).add()

def ATR(bt):
    if bt.index < 15: # Assumes n+1 periods
        return
    
    high = bt.data["High"].iloc[bt.index-15:bt.index].to_numpy()
    low = bt.data["Low"].iloc[bt.index-15:bt.index].to_numpy()
    close = bt.data["Close"].iloc[bt.index-15:bt.index].to_numpy()
    atr = talib.ATR(high, low, close, timeperiod=14)[-1]

    #print("ATR: {:.2f}".format(atr))
    return atr

def SMACrossover(bt):
    if bt.index < 21 or bt.index >= bt.data.shape[0]-1: # Assumes n+1 periods, and ignore final
        return

    nparray = bt.data["Close"].iloc[bt.index-21:bt.index].to_numpy()
    short_sma = talib.SMA(nparray, 10)
    long_sma = talib.SMA(nparray, 20)

    sma_buy = ((short_sma[-2] <= long_sma[-2]) and (short_sma[-1] >= long_sma[-1]))
    sma_sell = ((short_sma[-2] >= long_sma[-1]) and (short_sma[-1] <= long_sma[-1]))

    atr = ATR(bt)

    if sma_buy == True:
        # SHORTBUY(bt, 1).add()
        # LONGBUY(bt, 1).add()
        # SHORTBUY(bt, bt.quantity_owed).add()
        # LONGBUY(bt, math.floor(bt.balance/bt.price())).add()

        success = LONGBUY(bt, math.floor(0.998*bt.balance/bt.price()), commission=0.002).add()
        # success = LONGBUY(bt, math.floor(bt.balance/bt.price())).add()
        if success:
            tp = LONGSELL(bt, bt.quantity_held, limit = bt.price() + 1.5*atr, commission=0.002)
            sl = STOPSELL(bt, bt.quantity_held, limit = bt.price() - 1.5*atr, commission=0.002)
            OCO(bt, tp, sl).add()

    elif sma_sell == True:
        # LONGSELL(bt, bt.quantity_held).add()
        # SHORTSELL(bt, 1).add()
        # LONGSELL(bt, bt.quantity_held, commission=0.002).add()

        success = SHORTSELL(bt, math.floor(0.998*bt.balance/bt.price()), commission=0.002).add()
        # success = SHORTSELL(bt, math.floor(bt.balance/bt.price())).add()
        if success:
            tp = SHORTBUY(bt, bt.quantity_owed, limit = bt.price() - 1.5*atr, commission=0.002)
            sl = STOPBUY(bt, bt.quantity_owed, limit = bt.price() + 1.5*atr, commission=0.002)
            OCO(bt, tp, sl).add()
        
# =============================================================================

if __name__ == "__main__":
    bt = Backtest("datasets/GOOG.csv", SMACrossover, 10000)
    bt.run()
    bt.report()
    
# -----------------------------------------------------------------------------

# RSI, UTCUSD, Long, 1 BTC (100000)
# Equity: 105455.68359
# Positions: 4
# Win: 50%

# RSI, UTCUSD, Long and Short, 1 BTC (100000)
# Equity: 82002.92187
# Positions: 8
# Win: 25%

# RSI, GOOG, Long, Balance (100000)
# Equity: 117781.79
# Positions: 23

# RSI, GOOG, Long and Short, Balance (100000)
# Equity: 15958.03
# Positions: 47

# SMACross, UTCUSD, Long, 1 BTC (100000)
# Equity: 92232.80
# Positions: 8

# SMACross, UTCUSD, Long and Short, 1 BTC (100000)
# Equity: 53438.43
# Positions: 16

# SMACross + 1.5 ATR TP and SL, UTCUSD, Long and Short, Balance (100000)
# Equity: 71781.71
# Positions: 16
# Win: 43.75%

# REPLICATE
# SMACross, GOOG, Long, Balance (10000)
# Equity: 65401.80
# Positions: 37
# Win: 64.86%
# With Commission of 0.002:
# Equity: 60940.00
# Commissions: 4787.20

# SMACross + 1.5 ATR TP and SL, GOOG, Long, Balance (10000)
# Equity: 20521.74
# Positions: 46
# Win: 67.39%

# SMACross + 1.5 ATR TP and SL, GOOG, Long and Short, Balance (10000)
# Equity: 19019.04
# Positions: 84
# Win: 58.33%
# With Commission of 0.002:
# Equity: 13222.73
# Commissions: 4027.28
