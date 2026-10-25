import re
import warnings
from pathlib import Path
import pandas as pd

from src.config import OZON_COMMISSION_CAP_RATIO, OZON_RAW_DIR
from src.market import clean_columns, find_col, norm_sku, num

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')


def read_ozon_unit(ozon_dir: Path = OZON_RAW_DIR):
    """
    Считывание юнит-экономики Ozon с отловом ошибок.
    """
    files = sorted(ozon_dir.rglob('Юнит-экономика_*.xlsx'))
    frames = []
    errors = []

    for p in files:
        try:
            raw = pd.read_excel(p, sheet_name='Юнит-экономика', header=None, nrows=1, engine='openpyxl')
            text = str(raw.iloc[0, 0])
            m = re.search(r'(\d{2}\.\d{2}\.\d{4})-(\d{2}\.\d{2}\.\d{4})', text)
            start = pd.to_datetime(m.group(1), dayfirst=True) if m else pd.NaT
            end = pd.to_datetime(m.group(2), dayfirst=True) if m else pd.NaT

            d = clean_columns(pd.read_excel(p, sheet_name='Юнит-экономика', header=3, engine='openpyxl'))
            sku = find_col(d, ['Артикул'])
            d = d[d[sku].notna() & ~d[sku].astype(str).str.contains('итого', case=False, na=False)].copy()

            d['период'] = start
            d['период_месяц_год'] = start.to_period('M').strftime('%m.%Y')
            d['полный_месяц'] = (start.day == 1 and end == start + pd.offsets.MonthEnd(0))
            d['__source_file'] = p.name
            frames.append(d)
        except Exception as e:
            errors.append({'file': p.name, 'error': str(e)})

    if errors:
        print(f"⚠️ Предупреждение: при чтении юнит-экономики Ozon возникло {len(errors)} ошибок.")

    df_combined = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    meta = {
        'файлов': len(files),
        'ошибок': len(errors),
        'неполных': [p.name for p in files if '01.07.2026-07.07.2026' in p.name]
    }
    return df_combined, meta


def read_ozon_accrual(ozon_dir: Path = OZON_RAW_DIR):
    """
    Считывание начислений Ozon и защита от аномальных комиссий.
    """
    files = sorted(ozon_dir.rglob('Отчет по товарам за период *.xlsx'))
    frames = []
    errors = []

    for p in files:
        try:
            d = clean_columns(pd.read_excel(p, sheet_name='Начисления', header=0, engine='openpyxl'))
            d['__source_file'] = p.name
            frames.append(d)
        except Exception as e:
            errors.append({'file': p.name, 'error': str(e)})

    d = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if d.empty:
        return d, {'файлов': 0, 'строк': 0, 'аномалий_комиссии': 0, 'комиссия_до': 0.0, 'комиссия_после': 0.0}

    date = find_col(d, ['Дата начисления'])
    d[date] = pd.to_datetime(d[date], errors='coerce')
    d['период'] = d[date].dt.to_period('M').dt.to_timestamp()

    sales = num(d[find_col(d, ['За продажу или возврат до вычета комиссий и услуг'])])
    comm = num(d[find_col(d, ['Вознаграждение Ozon'])])

    # Защита от аномалий комиссии по порогу из config.py (не более 50%)
    outlier = (sales.abs() > 0) & (comm.abs() > sales.abs() * OZON_COMMISSION_CAP_RATIO)
    d['комиссия_скорректированная'] = comm.where(~outlier, -sales.abs() * OZON_COMMISSION_CAP_RATIO)

    meta = {
        'файлов': len(files),
        'строк': len(d),
        'ошибок': len(errors),
        'аномалий_комиссии': int(outlier.sum()),
        'комиссия_до': float(comm.sum()),
        'комиссия_после': float(d['комиссия_скорректированная'].sum())
    }
    return d, meta


def read_ozon_stock(ozon_dir: Path = OZON_RAW_DIR):
    """
    Считывание складских остатков Ozon.
    Ищет колонки по ключевым фразам из описательной шапки Ozon
    с надежной подстраховкой на случай изменения подсказок.
    """
    oz = next(ozon_dir.rglob('Управление остатками*.xlsx'))
    raw = pd.read_excel(oz, sheet_name='Товары', header=3, engine='openpyxl')
    ozdf = clean_columns(raw)

    # Фильтруем технические строки шаблона
    first_col = ozdf.columns[0]
    ozdf = ozdf[~ozdf[first_col].astype(str).str.contains('Номер артикула|Нередактируемое', na=False)].copy()

    # Ищем по фразам из длинной шапки Ozon
    try:
        art_col = find_col(ozdf, ['Номер артикула', 'Артикул'])
        name_col = find_col(ozdf, ['Название товара', 'Наименование'])
        status_col = find_col(ozdf, ['Соотношение спроса', 'Статус ликвидности', 'Ликвидность'])
        daily_sales_col = find_col(ozdf, ['Делим количество', 'Среднесуточные продажи', 'FBO'])
        no_sales_days_col = find_col(ozdf, ['дней подряд товар был без', 'Дней без продаж'])
        stock_col = find_col(ozdf, ['доступно к продаже', 'Текущий остаток', 'Остаток'])

        result_df = pd.DataFrame({
            'артикул': ozdf[art_col],
            'название': ozdf[name_col],
            'статус_ликвидности': ozdf[status_col],
            'среднесуточные_продажи': num(ozdf[daily_sales_col]),
            'дней_без_продаж': num(ozdf[no_sales_days_col]),
            'остаток': num(ozdf[stock_col])
        })
    except Exception:
        # Резервный фолбэк по индексам, если Ozon изменит текст подсказки
        sub = ozdf.iloc[:, [0, 1, 5, 7, 8, 9]].copy()
        sub.columns = ['артикул', 'название', 'статус_ликвидности', 'среднесуточные_продажи', 'дней_без_продаж', 'остаток']
        sub['среднесуточные_продажи'] = num(sub['среднесуточные_продажи'])
        sub['дней_без_продаж'] = num(sub['дней_без_продаж'])
        sub['остаток'] = num(sub['остаток'])
        result_df = sub

    return result_df, oz.name