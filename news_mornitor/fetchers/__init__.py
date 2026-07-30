from news_mornitor.fetchers.base import BaseFetcher
from news_mornitor.fetchers.binance_square import BinanceSquareFetcher
from news_mornitor.fetchers.bitget_square import BitgetSquareFetcher
from news_mornitor.fetchers.manager import FetcherManager
from news_mornitor.fetchers.okx_square import OkxSquareFetcher

__all__ = [
    "BaseFetcher",
    "BinanceSquareFetcher",
    "BitgetSquareFetcher",
    "OkxSquareFetcher",
    "FetcherManager",
]
