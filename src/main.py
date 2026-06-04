import pyupbit
import pandas as pd
import numpy as np
import time
import math
import threading
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

ACCESS_KEY = os.getenv("ACCESS_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
TICKER = os.getenv("TICKER", "KRW-XRP")
INTERVAL = os.getenv("INTERVAL", "minute5")

# Validation
if not ACCESS_KEY or not SECRET_KEY:
    raise ValueError("ERROR: ACCESS_KEY and SECRET_KEY must be set in .env file")

BUY_WEIGHTS = [0.4, 0.6]
MAX_HOLDING_TIME = 45
upbit = pyupbit.Upbit(ACCESS_KEY, SECRET_KEY)

# Global variables
current_buy_step = 0
last_buy_time = None
manual_cmd = None
monitor_print_time = 0
last_market_state = None
BUY_TIMEOUT_SECONDS = 30
REBUY_DROP_THRESHOLD = 0.005
last_buy_candle_time = None
last_sell_price = 0
last_sell_time = None


def get_total_balance(ticker):
    """주문 대기중인 물량까지 포함한 총 보유량 조회"""
    try:
        currency = ticker.split('-')[1]
        balances = upbit.get_balances()
        for b in balances:
            if b['currency'] == currency:
                return float(b['balance']) + float(b['locked'])
        return 0
    except:
        return 0


def cancel_open_orders(ticker):
    """미체결 주문 전량 취소"""
    try:
        orders = upbit.get_order(ticker)
        if orders:
            print(f" 미체결 주문 {len(orders)}건 취소...")
            for order in orders:
                upbit.cancel_order(order['uuid'])
                time.sleep(0.1)
    except:
        pass


def get_tick_size(price):
    if price < 10:
        return 0.01
    if price < 100:
        return 0.1
    if price < 1000:
        return 1
    if price < 10000:
        return 1
    if price < 100000:
        return 10
    if price < 500000:
        return 50
    if price < 1000000:
        return 100
    return 1000


def get_smart_entry_price(ticker):
    """매수벽 + 3호가 계산"""
    try:
        orderbook = pyupbit.get_orderbook(ticker)
        bids = orderbook['orderbook_units']
        max_vol = 0
        wall_price = 0
        for i in range(10):
            bid_vol = bids[i]['bid_size']
            if bid_vol > max_vol:
                max_vol = bid_vol
                wall_price = bids[i]['bid_price']
        if wall_price == 0:
            return bids[0]['bid_price']
        current_tick = wall_price
        for _ in range(3):
            current_tick += get_tick_size(current_tick)
        smart_price = current_tick
        ask_price = orderbook['orderbook_units'][0]['ask_price']
        if smart_price >= ask_price:
            return ask_price
        return smart_price
    except:
        return pyupbit.get_current_price(ticker)


def execute_smart_buy(ticker, amount, desc="조건진입"):
    try:
        smart_price = get_smart_entry_price(ticker)
        curr_price = pyupbit.get_current_price(ticker)
        orderbook = pyupbit.get_orderbook(ticker)
        ask_price = orderbook['orderbook_units'][0]['ask_price']
        is_market = False
        if smart_price >= ask_price:
            is_market = True
            target_price = ask_price
        else:
            target_price = smart_price
        print(f"\n [매수 실행] {desc}")
        print(f"   ├  투입 금액 : {amount:,.0f} KRW")
        print(f"   ├  주문 가격 : {target_price:,.0f} KRW (현재가: {curr_price:,.0f})")
        print(f"   └  주문 타입 : {' 시장가' if is_market else ' 지정가(매수벽+3호가)'}")
        if is_market:
            ret = upbit.buy_market_order(ticker, amount)
            if ret and 'uuid' in ret:
                print(f"    [체결 완료] UUID: {ret['uuid'][:8]}...")
                return True
            print(f"    [주문 실패] {ret}")
            return False
        volume = amount / smart_price
        ret = upbit.buy_limit_order(ticker, smart_price, volume)
        if ret is None or 'uuid' not in ret:
            print("    [요청 실패] API 응답 없음")
            return False
        uuid = ret['uuid']
        for i in range(BUY_TIMEOUT_SECONDS // 2):
            time.sleep(2)
            order_info = upbit.get_order(uuid)
            if order_info is None:
                continue
            state = order_info.get('state')
            if state == 'done':
                try:
                    exec_vol = float(order_info.get('executed_volume', 0))
                    paid_fee = float(order_info.get('paid_fee', 0))
                    real_avg = (amount - paid_fee) / exec_vol if exec_vol > 0 else smart_price
                    print(f"    [체결 완료] 평단: {real_avg:,.0f}원 (대기 {i*2}초)")
                except:
                    print(f"    [체결 완료] 상세 정보 수신 지연")
                return True
            if state == 'cancel':
                print("    [주문 취소됨]")
                return False
        print("    [시간 초과] 주문 취소 후 잔량 확인...")
        upbit.cancel_order(uuid)
        time.sleep(1)
        final_info = upbit.get_order(uuid)
        if final_info and float(final_info.get('executed_volume', 0)) > 0:
            print("    [부분 체결] 일부 물량 확보 성공")
            return True
        return False
    except Exception as e:
        print(f"    [에러 발생] {e}")
        return False


def execute_sell_with_log(ticker, volume, profit_rate, desc="익절"):
    try:
        curr_price = pyupbit.get_current_price(ticker)
        est_total = volume * curr_price
        print(f"\n [매도 실행] {desc}")
        print(f"   ├  현재 수익률 : {profit_rate*100:+.2f}%")
        print(f"   └  매도 추정액 : {est_total:,.0f} KRW (수량: {volume:.4f})")
        ret = upbit.sell_market_order(ticker, volume)
        if ret and 'uuid' in ret:
            time.sleep(0.5)
            print(f"    [매도 성공] 확정 수익률: {profit_rate*100:+.2f}%")
            return True
        elif ret and 'error' in ret:
            print(f"    [매도 실패] {ret['error'].get('message')}")
            return False
        else:
            print(f"    [매도 실패] 응답 없음")
            return False
    except Exception as e:
        print(f"    [매도 에러] {e}")
        return False


def get_all_indicators(ticker, interval, count=200):
    try:
        df = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
        if df is None:
            return None
        close = df['close']
        high = df['high']
        low = df['low']
        volume = df['volume']
        df['EMA5'] = close.ewm(span=5, adjust=False).mean()
        df['EMA12'] = close.ewm(span=12, adjust=False).mean()
        df['EMA20'] = close.ewm(span=20, adjust=False).mean()
        df['EMA60'] = close.ewm(span=60, adjust=False).mean()
        df['EMA120'] = close.ewm(span=120, adjust=False).mean()
        df['VolMA20'] = volume.rolling(window=20).mean()
        df['BB_Mid'] = close.rolling(window=20).mean()
        std = close.rolling(window=20).std()
        df['BB_Upper'] = df['BB_Mid'] + (2 * std)
        df['BB_Lower'] = df['BB_Mid'] - (2 * std)
        df['BB_Width'] = (df['BB_Upper'] - df['BB_Lower']) / (df['BB_Mid'] + 1e-8)
        env_ratio = 0.006
        df['Env_Upper'] = df['EMA20'] * (1 + env_ratio)
        df['Env_Lower'] = df['EMA20'] * (1 - env_ratio)
        df['Donch_Upper'] = high.rolling(window=20).max()
        delta = close.diff(1)
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=13, adjust=False).mean()
        avg_loss = loss.ewm(com=13, adjust=False).mean()
        rs = avg_gain / (avg_loss + 1e-8)
        df['RSI'] = 100 - (100 / (1 + rs))
        min_rsi = df['RSI'].rolling(window=14).min()
        max_rsi = df['RSI'].rolling(window=14).max()
        stoch_raw = (df['RSI'] - min_rsi) / (max_rsi - min_rsi + 1e-8)
        df['Stoch_K'] = stoch_raw.rolling(window=3).mean().clip(0, 1) * 100
        df['Stoch_D'] = df['Stoch_K'].rolling(window=3).mean()
        tp = (high + low + close) / 3
        sma_tp = tp.rolling(20).mean()
        mad = (tp - sma_tp).abs().rolling(20).mean()
        df['CCI'] = (tp - sma_tp) / (0.015 * mad + 1e-8)
        rmf = tp * volume
        pmf = rmf.where(tp > tp.shift(1), 0)
        nmf = rmf.where(tp < tp.shift(1), 0)
        mfi_ratio = pmf.rolling(window=14).sum() / (nmf.rolling(window=14).sum() + 1e-8)
        df['MFI'] = 100 - (100 / (1 + mfi_ratio))
        df['MACD'] = df['EMA12'] - close.ewm(span=26, adjust=False).mean()
        df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['ATR'] = tr.ewm(alpha=1/14, adjust=False).mean()
        up = high.diff()
        down = -low.diff()
        pdm = up.where((up > down) & (up > 0), 0)
        ndm = down.where((down > up) & (down > 0), 0)
        tr_s = tr.ewm(alpha=1/14, adjust=False).mean()
        pdm_s = pdm.ewm(alpha=1/14, adjust=False).mean()
        ndm_s = ndm.ewm(alpha=1/14, adjust=False).mean()
        df['Plus_DI'] = (pdm_s / (tr_s + 1e-8)) * 100
        df['Minus_DI'] = (ndm_s / (tr_s + 1e-8)) * 100
        df['ADX'] = (100 * (df['Plus_DI'] - df['Minus_DI']).abs() / (df['Plus_DI'] + df['Minus_DI'] + 1e-8)).ewm(
            alpha=1/14, adjust=False).mean()
        hl_range = high - low
        ema9 = hl_range.ewm(span=9).mean()
        ema9_2 = ema9.ewm(span=9).mean()
        df['Mass_Index'] = (ema9 / (ema9_2 + 1e-8)).rolling(25).sum()
        mf_mult = ((close - low) - (high - close)) / (high - low + 1e-8)
        df['CMF'] = (mf_mult * volume).rolling(20).sum() / (volume.rolling(20).sum() + 1e-8)
        df['Disparity'] = (close / df['EMA20']) * 100
        df['Dump_Rate'] = ((df['open'] - close) / df['open']).clip(lower=0)
        df.dropna(inplace=True)
        try:
            df_day = pyupbit.get_ohlcv(ticker, interval="day", count=2)
            if df_day is not None:
                prev = df_day.iloc[-2]
                pp = (prev['high'] + prev['low'] + prev['close']) / 3
                df['Pivot_P'] = pp
                df['Pivot_R1'] = (2 * pp) - prev['low']
                df['Pivot_S1'] = (2 * pp) - prev['high']
                df['Pivot_R2'] = pp + (prev['high'] - prev['low'])
            else:
                raise Exception
        except:
            df['Pivot_P'] = df['Pivot_R1'] = df['Pivot_S1'] = df['Pivot_R2'] = 0
        return df
    except:
        return None


class MarketAnalyzer:
    def __init__(self, df):
        self.df = df
        self.curr = df.iloc[-1]

    def analyze(self, prev_state=None):
        c = self.curr
        trend_score = 0
        if c['close'] > c['EMA120']:
            trend_score += 3
        else:
            trend_score -= 3
        if c['EMA5'] > c['EMA20']:
            trend_score += 2
        else:
            trend_score -= 2
        if c['Plus_DI'] > c['Minus_DI']:
            trend_score += 2
        else:
            trend_score -= 2
        if c['ADX'] > 25:
            trend_score *= 1.2
        elif c['ADX'] < 15:
            trend_score *= 0.5
        if c['MACD_Hist'] > 0:
            trend_score += 1
        else:
            trend_score -= 1
        mom_score = 0
        if c['RSI'] > 55:
            mom_score += 2
        elif c['RSI'] < 45:
            mom_score -= 2
        if c['CCI'] > 100:
            mom_score += 3
        elif c['CCI'] < -100:
            mom_score -= 3
        elif c['CCI'] > 0:
            mom_score += 1
        if c['CMF'] > 0.05:
            mom_score += 2
        elif c['CMF'] < -0.05:
            mom_score -= 2
        danger_signal = False
        if c['Mass_Index'] > 27 or c['Mass_Index'] < 24.5:
            danger_signal = True
        if c['Disparity'] > 101.5:
            danger_signal = True
        if c['Pivot_R1'] > 0 and c['high'] >= c['Pivot_R1'] * 0.998:
            danger_signal = True
        energy_score = 0
        if c['BB_Width'] > 0.02:
            energy_score += 3
        elif c['BB_Width'] < 0.004:
            energy_score = -5
        if c['volume'] > c['VolMA20']:
            energy_score += 2
        if c['ATR'] > self.df.iloc[-2]['ATR']:
            energy_score += 1
        new_state = "SIDEWAYS_STABLE"
        if c['BB_Width'] < 0.004:
            return "SQUEEZE", {"trend": trend_score, "money": mom_score, "energy": energy_score}
        is_uptrend_aligned = c['EMA5'] > c['EMA20']
        if trend_score >= 5 and mom_score >= 4 and is_uptrend_aligned:
            if c['RSI'] > 75:
                new_state = "OVERHEATED"
            else:
                new_state = "BULL_TREND"
            if trend_score >= 7 and c['CCI'] > 150 and energy_score >= 3:
                new_state = "SUPER_BULL"
        elif trend_score < 0 and mom_score >= 6 and c['Plus_DI'] > c['Minus_DI']:
            new_state = "SIDEWAYS_VOLATILE"
        elif trend_score <= -4:
            if c['Dump_Rate'] > 0.01 and energy_score >= 3:
                new_state = "PANIC_SELL"
            else:
                new_state = "BEAR_TREND"
        else:
            if energy_score >= 2:
                new_state = "SIDEWAYS_VOLATILE"
            else:
                new_state = "SIDEWAYS_STABLE"
        if "BULL" in new_state and danger_signal:
            new_state = "SIDEWAYS_VOLATILE"
        if new_state in ["SIDEWAYS_STABLE", "BEAR_TREND"] and mom_score >= 3:
            new_state = "ACCUMULATION"
        return new_state, {"trend": trend_score, "money": mom_score, "energy": energy_score}


class TradingExecutor:
    def __init__(self, df, state, report):
        self.df = df
        self.curr = df.iloc[-1]
        self.prev = df.iloc[-2]
        self.state = state
        self.c = self.curr
        self.atr = self.curr['ATR']

    def check_buy_signal(self):
        """매수 신호 및 관망 사유 점검"""
        c = self.c
        p = self.prev
        if c['RSI'] >= 70:
            return False, 0, f"RSI 과열 관망 ({c['RSI']:.0f} >= 70)"
        if c['Stoch_K'] >= 75:
            return False, 0, f"스토캐스틱 과열 관망 (K:{c['Stoch_K']:.0f} >= 75)"
        if last_sell_price > 0 and last_sell_time is not None:
            time_passed = (datetime.now() - last_sell_time).total_seconds()
            if time_passed < 300:
                target_rebuy_price = last_sell_price * (1 - REBUY_DROP_THRESHOLD)
                if c['close'] > target_rebuy_price:
                    return False, 0, f"재진입 대기 ({300-time_passed:.0f}초 남음)"
        if self.state == "SQUEEZE":
            return False, 0, "스퀴즈 관망"
        if self.state in ["BEAR_TREND", "PANIC_SELL"]:
            is_falling = c['MACD_Hist'] < p['MACD_Hist'] and c['MACD_Hist'] < 0
            if is_falling and (c['Dump_Rate'] > 0.008 or c['RSI'] < 25):
                return False, 0, "폭포수 방어"
        if self.state == "SUPER_BULL":
            if c['ADX'] >= 35:
                if c['low'] <= c['EMA5']:
                    if c['RSI'] < 70 and c['Stoch_K'] < 75:
                        return True, c['EMA5'], " 5이평 눌림목"
                    else:
                        return False, 0, f"눌림목이나 지표 과열(RSI:{c['RSI']:.0f})"
                else:
                    return False, 0, f"5이평 눌림 대기 (괴리 {(c['close']/c['EMA5']-1)*100:.1f}%)"
            else:
                return False, 0, f"ADX 강세 대기 ({c['ADX']:.0f} < 35)"
        elif self.state == "BULL_TREND":
            support = max(c['BB_Mid'], c['EMA20'])
            if c['low'] <= support * 1.005:
                if c['Stoch_K'] < 55 and c['CMF'] > 0.05:
                    return True, support, " 지지 & 모멘텀 확인"
                else:
                    return False, 0, f"확신 부족 (K:{c['Stoch_K']:.0f}, CMF:{c['CMF']:.2f})"
            else:
                return False, 0, f"지지선 눌림 대기 (현재 {c['close']:.0f} > 지지 {support:.0f})"
        elif self.state == "SIDEWAYS_VOLATILE":
            if c['CCI'] > 100 and c['Plus_DI'] > c['Minus_DI']:
                if c['RSI'] < 60 and c['Stoch_K'] < 60:
                    return True, c['close'], " CCI 돌파 & 저점 확인"
                else:
                    return False, 0, f"CCI 돌파했으나 이미 고점 (RSI:{c['RSI']:.0f})"
            limit = min(c['Env_Lower'], c['Pivot_S1']) if c['Pivot_S1'] > 0 else c['Env_Lower']
            if c['low'] <= limit * 1.005:
                if c['RSI'] < 45:
                    return True, limit, " 엔벨로프 하단"
                else:
                    return False, 0, f"하단 근접했으나 RSI 높음({c['RSI']:.0f})"
            else:
                return False, 0, f"박스권/반등 기회 탐색 (CCI:{c['CCI']:.0f})"
        elif self.state == "ACCUMULATION":
            if c['close'] < c['EMA20']:
                if c['MFI'] < 30 and c['Stoch_K'] < 40:
                    return True, c['close'], " 저점 분할"
                else:
                    return False, 0, f"저점이나 지표 높음 (MFI:{c['MFI']:.0f})"
            else:
                return False, 0, "20이평 아래로 내려와야 함"
        elif self.state in ["PANIC_SELL", "BEAR_TREND"]:
            if c['Disparity'] < 97 and c['RSI'] < 25 and c['close'] < c['Env_Lower']:
                return True, c['close'], " 과매도 스나이핑"
            else:
                return False, 0, "과매도 심화 대기"
        return False, 0, "진입 조건 탐색 중..."

    def check_sell_signal(self, profit_rate):
        """매도 신호 점검"""
        c = self.c
        p = self.prev
        if c['Pivot_R2'] > 0 and c['high'] >= c['Pivot_R2']:
            return True, " 피봇 2차 저항 "
        if c['Dump_Rate'] > 0.015 and c['volume'] > c['VolMA20'] * 2:
            return True, " 대량거래 음봉 발생"
        if self.state == "SUPER_BULL":
            if c['close'] < c['EMA20']:
                return True, " 추세선(20선) 이탈"
            if p['RSI'] > 80 and c['RSI'] < 80:
                return True, " RSI 초과열 후 꺾임"
        elif self.state in ["BEAR_TREND", "PANIC_SELL"]:
            if c['high'] >= c['EMA5']:
                return True, " 하락장 기술적 반등 종료"
            if c['MACD_Hist'] < p['MACD_Hist']:
                return True, " 하락 모멘텀 재점화"
        else:
            if profit_rate > 0.002:
                if c['close'] < c['EMA5']:
                    return True, f" 5이평 이탈 (수익 {profit_rate*100:.2f}%)"
                if c['Stoch_K'] > 80 and c['Stoch_K'] < p['Stoch_K']:
                    return True, f" 스토캐스틱 꺾임 (수익 {profit_rate*100:.2f}%)"
            if self.state in ["SIDEWAYS_VOLATILE", "SIDEWAYS_STABLE"]:
                if c['high'] >= c['Env_Upper']:
                    return True, " 박스권 상단 터치"
        atr_sl_pct = -(self.atr * 1.5) / c['close']
        real_sl = max(min(atr_sl_pct, -0.015), -0.03)
        if profit_rate <= real_sl:
            return True, f" ATR 손절 ({real_sl*100:.2f}%)"
        return False, "홀딩 중 (수익 극대화 or 조건 대기)"


def input_listener():
    global manual_cmd
    while True:
        try:
            i = input().split()
            if not i:
                continue
            if i[0] == "취소":
                manual_cmd = {"type": "cancel_all"}
            elif i[0] == "매수":
                manual_cmd = {"type": "buy_market"}
            elif i[0] == "매도":
                manual_cmd = {"type": "sell_market"}
            elif len(i) == 2 and i[1] == "매수":
                manual_cmd = {"type": "buy_limit", "price": float(i[0])}
            elif len(i) == 2 and i[1] == "매도":
                manual_cmd = {"type": "sell_limit", "price": float(i[0])}
        except:
            pass


def print_startup_dashboard(ticker):
    try:
        print("\n" + "="*60)
        print(f" [UPBIT SCALPING BOT v1.2] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        krw = upbit.get_balance("KRW") or 0
        coin_total = get_total_balance(ticker)
        curr_price = pyupbit.get_current_price(ticker)
        avg_price = upbit.get_avg_buy_price(ticker)
        total_eval = krw + (coin_total * curr_price)
        profit_rate = (curr_price - avg_price) / avg_price * 100 if avg_price > 0 else 0
        print(f"  타겟 코인 : {ticker}")
        print(f"  총 추정자산: {total_eval:,.0f} KRW")
        print(f"  보유 현금 : {krw:,.0f} KRW")
        print(f"  보유 코인 : {coin_total:,.4f} {ticker.split('-')[1]} (평단: {avg_price:,.0f}원)")
        print(f"  현재 수익률: {profit_rate:+.2f}%")
        print("-" * 60)
        print(f"  스캘핑 설정: {INTERVAL} | 분할: {BUY_WEIGHTS} | 손절: 동적(ATR)")
        print("="*60 + "\n")
        return total_eval
    except Exception as e:
        print(f" 초기화 중 오류: {e}")
        return 0


if __name__ == "__main__":
    t = threading.Thread(target=input_listener)
    t.daemon = True
    t.start()
    print_startup_dashboard(TICKER)
    print(" 데이터 수집 및 지표 계산")
    last_market_state = None
    last_signal_time = 0
    monitor_print_time = time.time()
    while True:
        try:
            df = get_all_indicators(TICKER, INTERVAL)
            if df is None:
                time.sleep(1)
                continue
            analyzer = MarketAnalyzer(df)
            market_state, analysis_report = analyzer.analyze(prev_state=last_market_state)
            t_score = analysis_report.get("trend", 0)
            m_score = analysis_report.get("money", 0)
            e_score = analysis_report.get("energy", 0)
            krw = upbit.get_balance("KRW") or 0
            coin_total = get_total_balance(TICKER)
            coin_avail = upbit.get_balance(TICKER) or 0
            curr_price = pyupbit.get_current_price(TICKER)
            total_equity = krw + (coin_total * curr_price)
            ratio = (coin_total * curr_price) / total_equity if total_equity > 0 else 0
            real_step = 0
            if ratio >= 0.7:
                real_step = 2
            elif ratio >= 0.1:
                real_step = 1
            if real_step != current_buy_step:
                if real_step > current_buy_step:
                    last_buy_time = datetime.now()
                current_buy_step = real_step
            profit_rate = 0
            if coin_total * curr_price > 5000:
                avg = upbit.get_avg_buy_price(TICKER)
                profit_rate = (curr_price - avg) / avg
            if manual_cmd:
                cancel_open_orders(TICKER)
                time.sleep(0.5)
                c_type = manual_cmd['type']
                if "cancel" in c_type:
                    pass
                elif "buy" in c_type:
                    amt = krw * 0.9995 if current_buy_step == 1 else total_equity * BUY_WEIGHTS[current_buy_step]
                    if current_buy_step == 0:
                        amt = total_equity * BUY_WEIGHTS[0]
                    if krw >= 5000:
                        if "market" in c_type:
                            if execute_smart_buy(TICKER, amt, "수동매수"):
                                last_buy_time = datetime.now()
                        else:
                            price = manual_cmd['price']
                            ret = upbit.buy_limit_order(TICKER, price, amt / price)
                            if ret and 'uuid' in ret:
                                print(f" 지정가 매수 주문 완료 ({price})")
                            else:
                                print(" 매수 주문 실패")
                    else:
                        print(" 잔액 부족")
                elif "sell" in c_type:
                    time.sleep(0.2)
                    c_avail = upbit.get_balance(TICKER)
                    if c_avail > 0:
                        if "market" in c_type:
                            execute_sell_with_log(TICKER, c_avail, 0, "수동매도")
                        else:
                            price = manual_cmd['price']
                            ret = upbit.sell_limit_order(TICKER, price, c_avail)
                            if ret and 'uuid' in ret:
                                print(f" 지정가 매도 주문 완료 ({price})")
                            else:
                                print(" 매도 주문 실패")
                    else:
                        print(" 매도 가능 물량 없음")
                manual_cmd = None
                time.sleep(1)
                continue
            executor = TradingExecutor(df, market_state, analysis_report)
            cur = df.iloc[-1]
            k_val = cur['Stoch_K']
            rsi_val = cur['RSI']
            mfi_val = cur['MFI']
            should_print = False
            print_reason = ""
            if last_market_state is not None and market_state != last_market_state:
                should_print = True
                print_reason = f" {last_market_state} ➜ {market_state}"
            elif time.time() - last_signal_time > 60:
                signals = []
                if rsi_val <= 25:
                    signals.append(f"RSI과매도({rsi_val:.0f})")
                if k_val <= 15:
                    signals.append(f"Stoch바닥({k_val:.0f})")
                if cur['Dump_Rate'] >= 0.01:
                    signals.append("급락발생")
                if cur['volume'] > cur['VolMA20'] * 3:
                    signals.append("거래량폭발")
                if signals:
                    should_print = True
                    print_reason = f" {', '.join(signals)}"
                    last_signal_time = time.time()
            if not should_print and (time.time() - monitor_print_time > 300):
                should_print = True
                print_reason = " 이상 무"
            if should_print:
                icon = ""
                if "BULL" in market_state:
                    icon = ""
                elif "BEAR" in market_state or "PANIC" in market_state:
                    icon = ""
                elif "SIDEWAYS" in market_state:
                    icon = ""
                cmf_icon = "" if cur['CMF'] > 0 else ""
                wait_reason = ""
                if coin_avail * curr_price > 5000:
                    _, wait_reason = executor.check_sell_signal(profit_rate)
                elif krw > 5000:
                    _, _, wait_reason = executor.check_buy_signal()
                log_msg = (
                    f"[{datetime.now().strftime('%H:%M')}] {print_reason}\n"
                    f"   └ {icon} {market_state:<10} (T:{t_score}/M:{m_score}/E:{e_score}) | "
                    f"Price: {curr_price:,.0f} | "
                    f"RSI:{rsi_val:.0f} MFI:{mfi_val:.0f}{cmf_icon} K:{k_val:.0f} | "
                    f"수익: {profit_rate*100:+.2f}% (Step{current_buy_step})\n"
                    f"    {wait_reason}"
                )
                print(log_msg)
                monitor_print_time = time.time()
                last_market_state = market_state
            if coin_avail * curr_price > 5000:
                should_sell, reason = executor.check_sell_signal(profit_rate)
                if should_sell:
                    if execute_sell_with_log(TICKER, coin_avail, profit_rate, reason):
                        last_sell_price = curr_price
                        last_sell_time = datetime.now()
            if krw > 5000 and current_buy_step < 2:
                current_candle_time = df.index[-1]
                if last_buy_candle_time == current_candle_time:
                    time.sleep(1)
                    continue
                should_buy, buy_p, reason = executor.check_buy_signal()
                if should_buy:
                    if current_buy_step == 1:
                        avg = upbit.get_avg_buy_price(TICKER)
                        if curr_price > avg * 0.995:
                            continue
                    amt = krw * 0.9995 if current_buy_step == 1 else total_equity * BUY_WEIGHTS[current_buy_step]
                    if current_buy_step == 0:
                        amt = total_equity * BUY_WEIGHTS[0]
                    if execute_smart_buy(TICKER, amt, reason):
                        last_buy_time = datetime.now()
                        last_buy_candle_time = current_candle_time
            time.sleep(2)
        except Exception as e:
            print(f"ERR: {e}")
            time.sleep(3)
