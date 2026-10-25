import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    INTERIM_DIR,
    MARKET_RAW_DIR,
    OZON_RAW_DIR,
    RAW_DIR,
    ensure_directories
)
from src.market import (
    find_col,
    num,
    read_market_funnel,
    read_market_orders,
    read_market_statistics,
    read_market_stock
)
from src.ozon import (
    read_ozon_accrual,
    read_ozon_stock,
    read_ozon_unit
)


def sanitize_for_parquet(df: pd.DataFrame) -> pd.DataFrame:
    """
    Приводит столбцы типа object к единообразному строковому типу.
    Защищает от ошибки ArrowInvalid при смешивании чисел и строк из разных Excel-файлов.
    """
    if df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == 'object':
            out[col] = out[col].apply(lambda x: str(x) if pd.notna(x) else None)
    return out


def extract_all():
    """
    Слой 1: Extract.
    Считывает сырые выгрузки и сохраняет стандартизированные срезы в interim/*.parquet.
    """
    ensure_directories()

    print(" [1/4] Сбор данных Яндекс Маркета...")
    stats, _ = read_market_statistics(MARKET_RAW_DIR)
    orders, _ = read_market_orders(MARKET_RAW_DIR)

    delivered_df = stats.get('delivered', pd.DataFrame()).copy()
    services_df = orders.get('services', pd.DataFrame()).copy()

    if not delivered_df.empty and not services_df.empty:
        order_col = find_col(delivered_df, ['Номер заказа'])
        serv_order_col = find_col(services_df, ['Номер заказа'])
        expense_col = find_col(services_df, ['Все услуги Маркета за заказы, ₽'])
        status_col = find_col(services_df, ['Статус заказа'], required=False)

        if status_col:
            services_df = services_df[services_df[status_col].astype(str).str.contains('Доставлен', case=False, na=False)].copy()

        services_df['расходы_маркета'] = num(services_df[expense_col])
        services_summary = services_df[[serv_order_col, 'расходы_маркета']].rename(
            columns={serv_order_col: order_col}
        ).groupby(order_col, as_index=False)['расходы_маркета'].sum()

        delivered_df = delivered_df.merge(services_summary, on=order_col, how='left')
        delivered_df['расходы_маркета'] = delivered_df['расходы_маркета'].fillna(0.0)

    delivered_df = sanitize_for_parquet(delivered_df)
    delivered_df.to_parquet(INTERIM_DIR / 'ym_raw.parquet', index=False)
    print(f"    Сохранено: interim/ym_raw.parquet ({len(delivered_df)} строк)")

    print(" [2/4] Сбор данных Ozon...")
    ozon_unit_df, _ = read_ozon_unit(OZON_RAW_DIR)
    ozon_unit_df = sanitize_for_parquet(ozon_unit_df)
    ozon_unit_df.to_parquet(INTERIM_DIR / 'ozon_raw.parquet', index=False)
    print(f"    Сохранено: interim/ozon_raw.parquet ({len(ozon_unit_df)} строк)")

    print(" [3/4] Сбор воронки продаж Маркета...")
    funnel_df, _ = read_market_funnel(RAW_DIR)
    funnel_df = sanitize_for_parquet(funnel_df)
    funnel_df.to_parquet(INTERIM_DIR / 'funnel_raw.parquet', index=False)
    print(f"    Сохранено: interim/funnel_raw.parquet ({len(funnel_df)} строк)")

    print(" [4/4] Сбор остатков на складах...")
    ozon_stock_df, _ = read_ozon_stock(OZON_RAW_DIR)
    market_stock_df, _ = read_market_stock(MARKET_RAW_DIR)

    ozon_stock_df['площадка'] = 'Ozon'
    market_stock_df['площадка'] = 'Яндекс Маркет'

    stocks_combined = pd.concat([ozon_stock_df, market_stock_df], ignore_index=True, sort=False)
    stocks_combined = sanitize_for_parquet(stocks_combined)
    stocks_combined.to_parquet(INTERIM_DIR / 'stock_raw.parquet', index=False)
    print(f"    Сохранено: interim/stock_raw.parquet ({len(stocks_combined)} строк)")

    print("\n Этап Extract успешно завершен! Все промежуточные файлы сохранены в interim/.\n")


if __name__ == '__main__':
    extract_all()