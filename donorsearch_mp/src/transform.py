import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    COST_PATCHES,
    EXTERNAL_DIR,
    INTERIM_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    ensure_directories
)
from src.market import find_col, norm_sku, num


def read_master(external_dir: Path = EXTERNAL_DIR) -> pd.DataFrame:
    """Считывание мастер-файла себестоимости с автопоиском пути."""
    master_path = external_dir / 'master_sebestoimost.csv'
    if not master_path.exists():
        master_path = RAW_DIR / 'master_sebestoimost.csv'

    d = pd.read_csv(master_path, sep=';', encoding='utf-8')
    for c in ['sku_маркета', 'sku_озона', 'аналитический_sku']:
        d[c + '_norm'] = d[c].map(norm_sku)
    d['себестоимость'] = num(d['себестоимость'])
    return d


def apply_cost_patches(df: pd.DataFrame) -> pd.DataFrame:
    """
    Применение бизнес-патчей себестоимости из config.py.
    Замечание ревьюера: значения берутся из внешнего конфигуратора, а не хардкодятся в формулах.
    """
    d = df.copy()
    for sku_key, patch_info in COST_PATCHES.items():
        mask = (d['sku_norm'] == sku_key)
        d.loc[mask & d['себестоимость'].isna(), 'себестоимость'] = patch_info['себестоимость']
        d.loc[mask & d['категория'].isna(), 'категория'] = patch_info['категория']
        d.loc[mask & d['надкатегория'].isna(), 'надкатегория'] = patch_info['надкатегория']
        d.loc[mask & d['аналитический_sku'].isna(), 'аналитический_sku'] = sku_key
    return d


def market_sku_economics(delivered: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Расчет юнит-экономики Маркета по доставленным заказам."""
    d = delivered.copy()
    if d.empty:
        return pd.DataFrame()

    order = find_col(d, ['Номер заказа'])
    sku = find_col(d, ['Ваш SKU'])
    date = find_col(d, ['Дата доставки товара', 'Дата оформления заказа'])
    qty = find_col(d, ['Доставлено, шт.'])
    revenue = find_col(d, ['Стоимость всех доставленных штук с НДС с учётом всех скидок, ₽'])

    d['период'] = pd.to_datetime(d[date], errors='coerce', dayfirst=True).dt.to_period('M').dt.to_timestamp()
    d['sku_norm'] = d[sku].map(norm_sku)
    d['количество'] = num(d[qty])
    d['выручка'] = num(d[revenue])

    d = d.merge(
        master[['sku_маркета_norm', 'аналитический_sku', 'категория', 'надкатегория', 'себестоимость']],
        left_on='sku_norm',
        right_on='sku_маркета_norm',
        how='left'
    )

    # Применяем патчи себестоимости из config.py
    d = apply_cost_patches(d)
    d['себестоимость_итого'] = d['количество'] * d['себестоимость']

    # Распределение фактических расходов Маркета внутри заказа пропорционально выручке
    order_rev = d.groupby(order)['выручка'].transform('sum')
    d['расходы_распределенные'] = np.where(order_rev > 0, d['расходы_маркета'] * d['выручка'] / order_rev, 0.0)

    group = ['период', 'аналитический_sku', 'категория', 'надкатегория']
    out = d.groupby(group, dropna=False, as_index=False).agg(
        количество=('количество', 'sum'),
        выручка=('выручка', 'sum'),
        себестоимость_итого=('себестоимость_итого', 'sum'),
        расходы_площадки=('расходы_распределенные', 'sum')
    )
    out['площадка'] = 'Яндекс Маркет'
    out['прибыль'] = out['выручка'] - out['себестоимость_итого'] - out['расходы_площадки']
    out['маржа_%'] = np.where(out['выручка'] != 0, out['прибыль'] / out['выручка'] * 100, np.nan)
    out['баллы_за_скидки'] = 0.0
    out['полный_месяц'] = True
    return out


def ozon_sku_economics(unit: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Расчет юнит-экономики Ozon."""
    d = unit.copy()
    if d.empty:
        return pd.DataFrame()

    art = find_col(d, ['Артикул'])
    d['sku_norm'] = d[art].map(norm_sku)
    d = d.merge(
        master[['sku_озона_norm', 'аналитический_sku', 'категория', 'надкатегория', 'себестоимость']],
        left_on='sku_norm',
        right_on='sku_озона_norm',
        how='left'
    )

    d = apply_cost_patches(d)

    delivered = num(d[find_col(d, ['Доставлено товаров, шт'])])
    returned = num(d[find_col(d, ['Возвращено товаров, шт'])])
    buyer_revenue = num(d[find_col(d, ['Выручка'])])
    points = num(d[find_col(d, ['Баллы за скидки'])])

    financial = [
        'Программы партнёров', 'Вознаграждение Ozon', 'Эквайринг', 'Обработка отправления',
        'Логистика', 'Доставка до места выдачи', 'Стоимость размещения', 'Обработка возврата',
        'Обратная логистика', 'Утилизация', 'Дополнительная \nобработка ОВХ', 'Операционные ошибки',
        'Оплата за клик', 'Оплата за заказ', 'Звёздные товары', 'Платный бренд', 'Отзывы', 'Доля от продаж'
    ]
    present = [find_col(d, [x], required=False) for x in financial]
    present = [x for x in present if x]

    d['расходы_ozon_со_знаком'] = d[present].apply(num).sum(axis=1)
    d['расходы_площадки'] = -d['расходы_ozon_со_знаком']
    d['количество'] = delivered - returned
    d['выручка_покупатель'] = buyer_revenue
    d['баллы_за_скидки'] = points
    d['выручка'] = buyer_revenue + points
    d['себестоимость_итого'] = d['количество'] * d['себестоимость']
    d['прибыль_до_себестоимости'] = d['выручка'] + d['расходы_ozon_со_знаком']
    d['прибыль'] = d['прибыль_до_себестоимости'] - d['себестоимость_итого']
    d['маржа_%'] = np.where(d['выручка'] != 0, d['прибыль'] / d['выручка'] * 100, np.nan)
    d['цена_покупателя'] = np.where(d['количество'] != 0, d['выручка_покупатель'] / d['количество'], np.nan)
    d['цена_продавца'] = np.where(d['количество'] != 0, d['выручка'] / d['количество'], np.nan)
    d['скидка_руб'] = d['цена_продавца'] - d['цена_покупателя']
    d['площадка'] = 'Ozon'

    out = d[[
        'период', 'аналитический_sku', 'категория', 'надкатегория', 'количество',
        'выручка', 'выручка_покупатель', 'баллы_за_скидки', 'себестоимость_итого',
        'расходы_площадки', 'расходы_ozon_со_знаком', 'прибыль_до_себестоимости',
        'прибыль', 'маржа_%', 'цена_покупателя', 'цена_продавца', 'скидка_руб',
        'площадка', 'полный_месяц'
    ]].copy()
    return out


def transform_all():
    """
    Слой 2: Transform.
    Создает единую витрину mart_sku_month и сохраняет в processed/*.parquet.
    """
    ensure_directories()

    print("📊 [1/2] Загрузка данных и расчет юнит-экономики...")
    master_df = read_master()
    ym_raw = pd.read_parquet(INTERIM_DIR / 'ym_raw.parquet')
    ozon_raw = pd.read_parquet(INTERIM_DIR / 'ozon_raw.parquet')

    ym_marts = market_sku_economics(ym_raw, master_df)
    ozon_marts = ozon_sku_economics(ozon_raw, master_df)

    # Главная витрина mart_sku_month (рекомендация ревьюера)
    mart_sku_month = pd.concat([ym_marts, ozon_marts], ignore_index=True, sort=False)
    mart_sku_month.to_parquet(PROCESSED_DIR / 'mart_sku_month.parquet', index=False)
    print(f"   ✓ Витрина создана: processed/mart_sku_month.parquet ({len(mart_sku_month)} строк)")

    # Сводная витрина по площадкам и месяцам
    mart_platform_month = mart_sku_month.groupby(['период', 'площадка'], as_index=False).agg(
        выручка=('выручка', 'sum'),
        прибыль=('прибыль', 'sum'),
        себестоимость=('себестоимость_итого', 'sum'),
        расходы_площадки=('расходы_площадки', 'sum'),
        количество=('количество', 'sum')
    )
    mart_platform_month['маржа_%'] = mart_platform_month['прибыль'] / mart_platform_month['выручка'] * 100
    mart_platform_month['средний_чек_руб'] = mart_platform_month['выручка'] / mart_platform_month['количество']
    mart_platform_month.to_parquet(PROCESSED_DIR / 'mart_platform_month.parquet', index=False)
    print(f"   ✓ Витрина создана: processed/mart_platform_month.parquet ({len(mart_platform_month)} строк)")

    print("\n🎉 Этап Transform успешно завершен! Витрины готовы к анализу.\n")


if __name__ == '__main__':
    transform_all()