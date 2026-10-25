import hashlib
import re
import unicodedata
import warnings
from pathlib import Path
import pandas as pd

from src.config import MARKET_RAW_DIR, RAW_DIR

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

MONTHS = {
    'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
    'май': 5, 'маи': 5, 'июнь': 6, 'июль': 7,
    'август': 8, 'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
}


# ==========================================
# 1. СЛУЖЕБНЫЕ ФУНКЦИИ (ОЧИСТКА И ПОИСК)
# ==========================================

def norm_text(x):
    """Нормализация текста: нижний регистр и удаление спецпробелов."""
    if pd.isna(x):
        return ''
    return unicodedata.normalize('NFKC', str(x)).replace('\xa0', ' ').strip().lower()


def norm_sku(x):
    """Нормализация артикулов для сквозного слияния."""
    return norm_text(x).replace('ё', 'е')


def md5(path: Path):
    """Хэширование содержимого для отсечения побайтных дубликатов файлов."""
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def num(s):
    """
    Приведение к числовому типу.
    Замечание ревьюера: fillna(0.0) применяется только для числовых метрик (выручка, штуки),
    где отсутствие записи экономически равно нулю.
    """
    return pd.to_numeric(s, errors='coerce').fillna(0.0)


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Удаление пустых столбцов и обработка дублирующихся заголовков."""
    out = df.copy()
    cols = []
    seen = {}
    for i, c in enumerate(out.columns):
        base = str(c).strip() if not pd.isna(c) else f'Пустая_{i}'
        n = seen.get(base, 0)
        seen[base] = n + 1
        cols.append(base if n == 0 else f'{base}__{n+1}')
    out.columns = cols
    return out.dropna(axis=1, how='all')


def find_col(df: pd.DataFrame, candidates: list, required: bool = True):
    """Универсальный поиск колонки по списку синонимов."""
    lookup = {norm_text(c): c for c in df.columns}
    for cand in candidates:
        if norm_text(cand) in lookup:
            return lookup[norm_text(cand)]
    for cand in candidates:
        cc = norm_text(cand)
        for k, v in lookup.items():
            if cc in k:
                return v
    if required:
        raise KeyError(f'Не найдена обязательная колонка: {candidates}; доступно: {list(df.columns)[:15]}')
    return None


def dated_from_name(path: Path):
    """Извлечение даты отчета из имени файла."""
    m = re.search(r'(\d{2}-\d{2}-\d{4})_(\d{2}-\d{2}-\d{4})', path.name)
    return pd.to_datetime(m.group(2), dayfirst=True) if m else pd.NaT


def read_dynamic(path: Path, sheet: str):
    """Поиск динамического заголовка в отчетах заказов."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None, engine='openpyxl')
    candidates = []
    for i, row in raw.iterrows():
        vals = [norm_text(v) for v in row.tolist()]
        if 'номер заказа' in vals or (sum(v != '' and v != 'nan' for v in vals) > 5 and any('заказ' in v for v in vals)):
            candidates.append(i)
    if not candidates:
        return pd.DataFrame(), None
    ix = next((i for i in candidates if 'номер заказа' in [norm_text(v) for v in raw.iloc[i].tolist()]), candidates[0])
    d = clean_columns(pd.read_excel(path, sheet_name=sheet, header=ix, engine='openpyxl'))
    return d, ix


# ==========================================
# 2. ЧТЕНИЕ ВЫГРУЗОК С ЛОГИРОВАНИЕМ ОШИБОК
# ==========================================

def read_market_statistics(market_dir: Path = MARKET_RAW_DIR):
    """
    Чтение статистики united_statistics_report_*.xlsx.
    Замечание ревьюера: логируем ошибки чтения файлов вместо их замалчивания.
    """
    files = sorted(market_dir.glob('united_statistics_report_*.xlsx'))
    mapping = {
        'Товары, переданные в доставку': 'in_transit',
        'Доставленные товары': 'delivered',
        'Невыкупленные товары': 'undelivered',
        'Возвращенные товары': 'returned'
    }
    coll = {v: [] for v in mapping.values()}
    errors = []
    stats = {'файлов': len(files), 'строк_до': {}, 'дубли': {}, 'ошибок': 0}

    for p in files:
        for sheet, typ in mapping.items():
            try:
                d = clean_columns(pd.read_excel(p, sheet_name=sheet, header=16, engine='openpyxl'))
            except Exception as e:
                errors.append({'file': p.name, 'sheet': sheet, 'error': str(e)})
                continue

            if len(d) == 0:
                continue
            order = find_col(d, ['Номер заказа'], required=False)
            if order is None:
                continue

            d = d[d[order].notna()].copy()
            d = d[~d[order].astype(str).str.contains('итого', case=False, na=False)]
            d['__source_file'] = p.name
            dt = find_col(d, ['Дата оформления заказа'], required=False)
            d['__freshness'] = pd.to_datetime(d[dt], errors='coerce', dayfirst=True).max() if dt else pd.NaT
            coll[typ].append(d)

    if errors:
        stats['ошибок'] = len(errors)
        print(f"⚠️ Предупреждение: при чтении статистики Маркета возникло {len(errors)} ошибок.")

    out = {}
    for typ, frames in coll.items():
        d = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        stats['строк_до'][typ] = len(d)
        if not d.empty:
            order = find_col(d, ['Номер заказа'])
            sku = find_col(d, ['Ваш SKU'])
            d = d.sort_values(['__freshness', '__source_file']).drop_duplicates([order, sku], keep='last').reset_index(drop=True)
        stats['дубли'][typ] = stats['строк_до'][typ] - len(d)
        out[typ] = d

    return out, stats


def read_market_orders(market_dir: Path = MARKET_RAW_DIR):
    """
    Чтение заказов и услуг Маркета с рекурсивным поиском и отловом сбоев.
    """
    all_files = sorted(market_dir.rglob('united_orders_*.xlsx'))
    keep = []
    hashes = set()
    skipped = []

    for p in all_files:
        h = md5(p)
        if h in hashes:
            skipped.append(p)
        else:
            hashes.add(h)
            keep.append(p)

    coll = {'transactions': [], 'services': []}
    headers = []
    errors = []

    for p in keep:
        fresh = dated_from_name(p)
        for sheet, typ in [('Транзакции по заказам и товарам', 'transactions'), ('Услуги и маржа по заказам', 'services')]:
            try:
                d, ix = read_dynamic(p, sheet)
            except Exception as e:
                errors.append({'file': p.name, 'sheet': sheet, 'error': str(e)})
                continue

            if d.empty:
                continue
            order = find_col(d, ['Номер заказа'], required=False)
            if order is None:
                continue

            d = d[d[order].notna()].copy()
            d = d[~d[order].astype(str).str.contains('итого', case=False, na=False)]
            d['__source_file'] = p.name
            d['__freshness'] = fresh
            coll[typ].append(d)
            headers.append((p.name, sheet, ix, len(d), list(d.columns)))

    out = {}
    before = {}
    dups = {}
    for typ, frames in coll.items():
        d = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
        before[typ] = len(d)
        if not d.empty:
            order = find_col(d, ['Номер заказа'])
            sku = find_col(d, ['Ваш SKU'], required=False)
            keys = [order, sku] if sku else [order]
            d = d.sort_values(['__freshness', '__source_file']).drop_duplicates(keys, keep='last').reset_index(drop=True)
        out[typ] = d
        dups[typ] = before[typ] - len(d)

    meta = {
        'файлов_всего': len(all_files),
        'файлов_уникальных': len(keep),
        'файлов_копий_исключено': len(skipped),
        'ошибок': len(errors),
        'строк_до': before,
        'дубли': dups,
        'headers': headers
    }
    return out, meta


def read_market_funnel(raw_dir: Path = RAW_DIR):
    """Чтение воронки продаж с рекурсивным охватом подпапок."""
    monthly = sorted([p for p in raw_dir.rglob('*.xlsx') if 'Аналитика продаж' in p.name])
    sales = sorted(raw_dir.rglob('sales_funnel_report_*.xlsx'))

    def content_hash(path):
        x = pd.read_excel(path, sheet_name='Аналитика продаж', header=0, engine='openpyxl').fillna('')
        return hashlib.md5(pd.util.hash_pandas_object(x.astype(str), index=False).values.tobytes()).hexdigest()

    monthly_hash = {content_hash(p) for p in monthly}
    use = list(monthly)
    added = []

    for p in sales:
        if content_hash(p) not in monthly_hash:
            use.append(p)
            added.append(p)

    def funnel_period_from_name(p):
        n = unicodedata.normalize('NFKD', p.stem).replace('\u0306', '').lower()
        m = re.search(r'(январь|февраль|март|апрель|маи|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\s+(20\d{2})', n)
        return pd.Timestamp(int(m.group(2)), MONTHS[m.group(1)], 1) if m else pd.NaT

    frames = []
    for p in use:
        d = clean_columns(pd.read_excel(p, sheet_name='Аналитика продаж', header=0, engine='openpyxl'))
        if 'Аналитика продаж -' in p.name:
            period = funnel_period_from_name(p)
        elif re.search(r'\(7\)', p.stem):
            period = pd.Timestamp(2026, 1, 1)
        else:
            period = pd.Timestamp(2025, 6, 1)
        d['период'] = period
        d['__source_file'] = p.name
        frames.append(d)

    return pd.concat(frames, ignore_index=True, sort=False), {
        'помесячных': len(monthly),
        'sales_funnel': len(sales),
        'уникальных_добавлено': len(added),
        'всего_использовано': len(use),
        'добавленные': [p.name for p in added]
    }


def read_market_stock(market_dir: Path = MARKET_RAW_DIR):
    """Считывание среза складских остатков Маркета."""
    ma = next(market_dir.rglob('fulfillment_offer_analytics*.xlsx'))
    madf = clean_columns(pd.read_excel(ma, sheet_name='Остатки по кластерам', header=6, engine='openpyxl'))
    return madf, ma.name