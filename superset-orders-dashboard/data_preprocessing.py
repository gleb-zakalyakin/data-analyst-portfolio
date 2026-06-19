import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

# --- 1. Подключение и загрузка данных ---

def load_table(table_name):
    print(f"Загружаем таблицу {table_name}...")
    file_path = f"{table_name}.csv"
    df = pd.read_csv(file_path)
    print(f"Таблица {table_name} загружена, размер: {df.shape}")
    return df

tables = ['orders', 'order_items', 'products', 'users', 'categories', 'transactions', 'reviews']

data = {}
for tbl in tables:
    data[tbl] = load_table(tbl)


# --- 2. Предобработка ---

total_dups = 0
for name, df in data.items():
    dups = df.duplicated().sum()
    total_dups += dups
    print(f'{name}: {dups} дубликатов')
    if dups > 0:
        df.drop_duplicates(inplace=True)

if total_dups == 0:
    print("Отличные новости: во всех таблицах дубликаты не найдены!")

data['orders']['order_date'] = pd.to_datetime(data['orders']['order_date'])
data['reviews']['review_date'] = pd.to_datetime(data['reviews']['review_date'])
data['transactions']['transaction_date'] = pd.to_datetime(data['transactions']['transaction_date'])
data['users']['registration_date'] = pd.to_datetime(data['users']['registration_date'])

neg_prices = data['products'][data['products']['price'] < 0].shape[0]
if neg_prices > 0:
    data['products'].loc[data['products']['price'] < 0, 'price'] = 0
print(f'products: исправлено {neg_prices} отрицательных цен')

for name, df in data.items():
    print(f"\n{name} — пропущенные значения:")
    print(df.isna().sum())

def categorize_rating(r):
    if r >= 4.5:
        return 'High'
    elif r >= 4:
        return 'Medium'
    else:
        return 'Low'

data['reviews']['rating_category'] = data['reviews']['rating'].apply(categorize_rating)
print('reviews: добавлен столбец rating_category')


# --- 3. Исследовательский анализ ---

def eda(df, columns):
    print(f"\nСтатистика по признакам: {columns}")
    print(df[columns].describe())
    for col in columns:
        fig, axs = plt.subplots(1, 2, figsize=(12, 4))
        sns.histplot(df[col].dropna(), kde=True, ax=axs[0])
        axs[0].set_title(f"Гистограмма {col}")
        sns.boxplot(x=df[col], ax=axs[1])
        axs[1].set_title(f"Boxplot {col}")
        plt.show()

eda(data['products'], ['price', 'stock_quantity'])

corr = data['products'][['price', 'stock_quantity']].corr()
print("\nКорреляционная матрица:")
print(corr)


# --- 4. Выгрузка обработанных данных ---

output_dir = 'exported_csv'
os.makedirs(output_dir, exist_ok=True)

orders_filtered = data['orders'][
    (data['orders']['order_date'] >= '2025-01-01') &
    (data['orders']['order_date'] <= '2025-06-01')
]

orders_path = os.path.join(output_dir, 'orders_filtered.csv')
orders_filtered.to_csv(orders_path, index=False)

print(f"Таблица заказов успешно выгружена: {orders_path}")
print(f"Строк: {orders_filtered.shape[0]}, Колонок: {orders_filtered.shape[1]}")
