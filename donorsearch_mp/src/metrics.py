import sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import (
    ABC_THRESHOLDS,
    EXTERNAL_DIR,
    INTERIM_DIR,
    OUTPUT_DIR,
    PROCESSED_DIR,
    TARGET_MARGIN_PCT,
    ensure_directories
)
from src.market import find_col, norm_sku, num
from src.transform import read_master


def calculate_abc_grades(df: pd.DataFrame, metric_col: str, prefix: str) -> pd.Series:
    """
    Расчет классов ABC по кумулятивному вкладу:
    - A: до 80% совокупного объема
    - B: следующие 15% (80-95%)
    - C: оставшиеся 5% (хвост распределения) либо нулевые значения.
    """
    s = df[metric_col].fillna(0.0)
    pos_mask = s > 0
    total = s[pos_mask].sum()

    grades = pd.Series('C', index=df.index)
    if total <= 0:
        return grades

    sorted_idx = s[pos_mask].sort_values(ascending=False).index
    cum_share = s.loc[sorted_idx].cumsum() / total

    a_idx = cum_share[cum_share <= ABC_THRESHOLDS['A']].index
    b_idx = cum_share[(cum_share > ABC_THRESHOLDS['A']) & (cum_share <= ABC_THRESHOLDS['B'])].index

    grades.loc[a_idx] = 'A'
    grades.loc[b_idx] = 'B'
    return grades


def calculate_metrics_and_recommendations():
    """
    Слой 3: Metrics & Recommendations.
    - ABC-анализ по выручке и прибыли
    - Матрица позиционирования SKU (Звезды, Двигатели объема, Скрытые бриллианты, Кандидаты на вылет)
    - Учет складской ликвидности и остатков
    - Формирование приоритизированного реестра управленческих решений
    """
    ensure_directories()

    print("[1/3] Построение матрицы SKU и ABC-анализа...")
    mart_sku_month = pd.read_parquet(PROCESSED_DIR / 'mart_sku_month.parquet')
    master = read_master()

    # Фильтрация полных календарных месяцев для сопоставимости периодов
    comparable = mart_sku_month[~((mart_sku_month['площадка'] == 'Ozon') & (mart_sku_month['полный_месяц'] == False))].copy()

    sku_total = comparable.groupby('аналитический_sku', dropna=True, as_index=False).agg(
        выручка=('выручка', 'sum'),
        прибыль=('прибыль', 'sum'),
        количество=('количество', 'sum')
    )

    registry = master[['аналитический_sku', 'категория', 'надкатегория', 'наименование']].drop_duplicates('аналитический_sku')
    
    # Добавление позиций из реестра корректировок себестоимости
    patched = mart_sku_month[['аналитический_sku', 'категория', 'надкатегория']].dropna(subset=['аналитический_sku']).drop_duplicates('аналитический_sku').copy()
    patched['наименование'] = patched['аналитический_sku']
    registry = pd.concat([registry, patched], ignore_index=True).drop_duplicates('аналитический_sku', keep='first')

    sku_total = registry.merge(sku_total, on='аналитический_sku', how='left')
    sku_total[['выручка', 'прибыль', 'количество']] = sku_total[['выручка', 'прибыль', 'количество']].fillna(0)
    sku_total['маржа_%'] = np.where(sku_total['выручка'] > 0, sku_total['прибыль'] / sku_total['выручка'] * 100, np.nan)

    # 1. Расчет грейдов ABC
    sku_total['ABC_выручка'] = calculate_abc_grades(sku_total, 'выручка', 'rev')
    sku_total['ABC_прибыль'] = calculate_abc_grades(sku_total, 'прибыль', 'prof')
    sku_total['ABC_грейд'] = sku_total['ABC_выручка'] + sku_total['ABC_прибыль']

    # 2. Сегментация по матрице выручка x маржинальность
    active = sku_total[sku_total['выручка'] > 0]
    rev_med = active['выручка'].median()
    margin_med = active['маржа_%'].median()

    def quadrant(r):
        if r['выручка'] == 0:
            return 'Кандидаты на вылет'
        hi_sales = r['выручка'] >= rev_med
        hi_margin = r['маржа_%'] >= margin_med
        if hi_sales and hi_margin:
            return 'Звёзды'
        if hi_sales:
            return 'Двигатели объёма'
        if hi_margin:
            return 'Скрытые бриллианты'
        return 'Кандидаты на вылет'

    sku_total['квадрант'] = sku_total.apply(quadrant, axis=1)

    print("[2/3] Сопоставление с остатками складов...")
    stocks = pd.read_parquet(INTERIM_DIR / 'stock_raw.parquet')

    # 1. Привязываем остатки Ozon к аналитическому SKU
    o = stocks[stocks['площадка'] == 'Ozon'].copy()
    if not o.empty:
        o['sku_norm'] = o['артикул'].map(norm_sku)
        o = o.merge(master[['sku_озона_norm', 'аналитический_sku']], left_on='sku_norm', right_on='sku_озона_norm', how='left')
        status_str = o.get('статус_ликвидности', pd.Series('', index=o.index)).astype(str)
        o['сигнал'] = np.where(status_str.str.contains('Избыточ|Без', case=False, na=False), 'избыточный / без продаж', '')
        o_clean = o[['аналитический_sku', 'остаток', 'сигнал']].copy()
    else:
        o_clean = pd.DataFrame(columns=['аналитический_sku', 'остаток', 'сигнал'])

    # 2. Привязываем остатки Маркета к аналитическому SKU
    m = stocks[stocks['площадка'] == 'Яндекс Маркет'].copy()
    if not m.empty:
        ssku_col = find_col(m, ['Ваш SSKU', 'SSKU', 'Артикул'], required=False)
        m['sku_norm'] = m[ssku_col].map(norm_sku) if ssku_col else m.get('артикул', pd.Series('', index=m.index)).map(norm_sku)
        m = m.merge(master[['sku_маркета_norm', 'аналитический_sku']], left_on='sku_norm', right_on='sku_маркета_norm', how='left')

        godny_col = find_col(m, ['Годный', 'остаток'], required=False)
        sales30_col = find_col(m, ['Продажи 30 дн', 'продажи_30д'], required=False)

        m_ost = num(m[godny_col]) if godny_col else num(m.get('остаток', 0))
        m_s30 = num(m[sales30_col]) if sales30_col else pd.Series(0.0, index=m.index)

        m['остаток'] = m_ost
        m['сигнал'] = np.where((m_ost > 0) & (m_s30 == 0), 'остаток без продаж', '')
        m_clean = m[['аналитический_sku', 'остаток', 'сигнал']].copy()
    else:
        m_clean = pd.DataFrame(columns=['аналитический_sku', 'остаток', 'сигнал'])

    # Объединяем остатки обеих площадок
    stocks_joined = pd.concat([o_clean, m_clean], ignore_index=True, sort=False).dropna(subset=['аналитический_sku'])

    stocks_summary = stocks_joined.groupby('аналитический_sku', as_index=False).agg(
        остаток_всего=('остаток', 'sum'),
        сигналы_остатков=('сигнал', lambda x: '; '.join(sorted(set(v for v in x if v))))
    )

    merged = sku_total.merge(stocks_summary, on='аналитический_sku', how='left')
    merged['остаток_всего'] = merged['остаток_всего'].fillna(0)
    merged['сигналы_остатков'] = merged['сигналы_остатков'].fillna('')

    print("[3/3] Формирование приоритизированной таблицы решений...")
    decision_rows = []

    for _, r in merged.iterrows():
        sku = r['аналитический_sku']
        name = r['наименование']
        cat = r['категория']
        rev = r['выручка']
        profit = r['прибыль']
        margin = r['маржа_%']
        quad = r['квадрант']
        abc = r['ABC_грейд']
        stock = r['остаток_всего']
        sig = r['сигналы_остатков']

        # Логика классификации проблем и формирования управленческих действий
        if quad == 'Двигатели объёма':
            prio = 1
            problem = 'Высокий оборот при маржинальности ниже целевой'
            action = 'Пересмотр ценообразования и структуры скидок'
            why = f'Товар категории {abc}: высокий спрос, но избыточная доля расходов площадки'
            effect = 'Повышение операционной рентабельности без потери объема продаж'
            conf = 'Высокая'

        elif 'остаток без продаж' in sig or ('избыточный' in sig and rev == 0):
            prio = 2
            problem = f'Замороженный товарный запас ({int(stock)} шт.) без динамики продаж'
            action = 'Остановка повторных закупок, ликвидация остатков'
            why = 'Иммобилизация оборотного капитала, риски платы за длительное платное хранение'
            effect = 'Высвобождение ликвидности и предотвращение прямых убытков'
            conf = 'Высокая'

        elif quad == 'Скрытые бриллианты':
            prio = 3
            problem = 'Высокая рентабельность при недостаточном объеме продаж'
            action = 'Увеличение рекламного продвижения и органической видимости'
            why = f'Маржа {margin:.1f}%: стабильная юнит-экономика при сдерживаемом трафике'
            effect = 'Масштабирование чистой прибыли при контролируемой стоимости привлечения'
            conf = 'Средняя'

        elif quad == 'Звёзды':
            prio = 4
            problem = 'Ключевой генератор прибыли: риски упущенной выгоды при аут-оф-стоке'
            action = 'Масштабирование каналов и поддержание неснижаемого остатка'
            why = f'Товар категории {abc}: формирует ядро выручки и финансовой устойчивости'
            effect = 'Защита рыночной доли и максимизация валового дохода'
            conf = 'Высокая'

        elif rev == 0:
            prio = 6
            problem = 'Позиция не представлена в структуре фактических продаж'
            action = 'Исключение из плана закупок'
            why = 'Отсутствие подтвержденного рыночного спроса'
            effect = 'Оптимизация бюджета оборотных средств'
            conf = 'Высокая'

        else:
            # Кандидаты на вылет с ненулевыми продажами
            prio = 5
            if stock > 0:
                problem = f'Низкая маржинальность и слабый спрос при наличии остатка ({int(stock)} шт.)'
                action = 'Кандидат на вывод (плановая распродажа стока)'
                why = 'Недостаточная рентабельность позиции при необходимости очистки склада'
                effect = 'Сокращение складских расходов и минимизация логистических затрат'
                conf = 'Средняя'
            else:
                problem = 'Низкая маржинальность и слабый спрос при нулевом остатке'
                action = 'Кандидат на вывод (завершение листинга)'
                why = 'Артикул демонстрирует устойчиво низкую операционную эффективность'
                effect = 'Концентрация ресурсов на высокомаржинальном пуле товаров'
                conf = 'Средняя'

        decision_rows.append({
            'Приоритет': prio,
            'SKU': sku,
            'Наименование': name,
            'Категория': cat,
            'Выручка, руб.': rev,
            'Прибыль, руб.': profit,
            'Маржа, %': margin,
            'Квадрант': quad,
            'ABC_грейд': abc,
            'Остаток, шт.': int(stock),
            'Проблема': problem,
            'Что делать': action,
            'Почему': why,
            'Ожидаемый эффект': effect,
            'Уверенность': conf
        })

    decision_df = pd.DataFrame(decision_rows)

    # Сортировка по приоритету и выручке
    decision_df = decision_df.sort_values(by=['Приоритет', 'Выручка, руб.'], ascending=[True, False]).reset_index(drop=True)

    # Сохранение итогового CSV-файла для бизнеса
    out_csv = OUTPUT_DIR / 'sku_recommendations.csv'
    decision_df.to_csv(out_csv, index=False, sep=';', encoding='utf-8-sig')

    # Сохранение сводной витрины для аналитического ноутбука
    summary_parquet = PROCESSED_DIR / 'mart_sku_summary.parquet'
    decision_df.to_parquet(summary_parquet, index=False)

    print(f"[OK] Таблица решений сформирована: {out_csv} ({len(decision_df)} SKU)")
    print(f"[OK] Сводная витрина сохранена: {summary_parquet}")
    print("\nРасчет метрик и формирование рекомендаций успешно завершены.\n")


if __name__ == '__main__':
    calculate_metrics_and_recommendations()