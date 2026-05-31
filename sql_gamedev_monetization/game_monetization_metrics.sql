/* Проект «Секреты Тёмнолесья»
 * Цель проекта: изучить влияние характеристик игроков и их игровых персонажей 
 * на покупку внутриигровой валюты «райские лепестки», а также оценить 
 * активность игроков при совершении внутриигровых покупок
 * 
 * Автор: Закалякин Глеб Олегович
 * Дата: 01.02.2025
 
  

-- Часть 1. Исследовательский анализ данных
-- Задача 1. Исследование доли платящих игроков

-- 1.1. Доля платящих пользователей по всем данным:
SELECT 
COUNT(id) AS all_players,
SUM(payer) AS payers,
SUM(payer)/COUNT(id)::NUMERIC  AS share_pay
FROM fantasy.users


-- 1.2. Доля платящих пользователей в разрезе расы персонажа:
SELECT
race,
COUNT(id) AS all_players,
SUM(payer) AS payers,
SUM(payer)/COUNT(id)::NUMERIC  AS share_pay
FROM fantasy.users AS u
LEFT JOIN fantasy.race AS r ON u.race_id=r.race_id
GROUP BY race
ORDER BY share_pay DESC

-- Задача 2. Исследование внутриигровых покупок
-- 2.1. Статистические показатели по полю amount:
-- Напишите ваш запрос здесь
SELECT 
COUNT(amount) AS all_purch,
SUM(amount) AS sum_purch,
MIN(amount) AS min_purch,
MAX(amount) AS max_purch,
AVG(amount) AS avg_purch,
PERCENTILE_DISC(0.5)
WITHIN GROUP(ORDER BY amount) AS med_purch,
STDDEV(amount) AS stddev_purch
FROM fantasy.events
-- 2.2: Аномальные нулевые покупки:
SELECT 
COUNT(amount) AS zero_absolute_purch,
COUNT(amount)::NUMERIC /(
SELECT
COUNT(amount)
FROM fantasy.events) AS share_zero_purch
FROM fantasy.events
WHERE amount=0

-- 2.3: Сравнительный анализ активности платящих и неплатящих игроков:
SELECT 
COUNT (DISTINCT u.id) FILTER (WHERE payer=0) AS who_dont_pay,
COUNT (DISTINCT u.id) FILTER (WHERE payer=1) AS who_pay,
COUNT(transaction_id) FILTER (WHERE payer=0)::numeric/COUNT (DISTINCT u.id) FILTER (WHERE payer=0) AS avg_transaction_not_pay,
COUNT(transaction_id) FILTER (WHERE payer=1)::NUMERIC/COUNT (DISTINCT u.id) FILTER (WHERE payer=1) AS avg_transaction_pay,
SUM(amount) FILTER (WHERE payer=0)::NUMERIC / COUNT(DISTINCT u.id) FILTER (WHERE payer=0) AS sum_amount_who_dont_pay,
SUM(amount) FILTER (WHERE payer=1)::NUMERIC / COUNT(DISTINCT u.id) FILTER (WHERE payer=1) AS sum_amount_who_pay
FROM fantasy.users AS u
LEFT JOIN fantasy.events AS e ON u.id=e.id
WHERE amount<>0

-- 2.4: Популярные эпические предметы:
SELECT game_items, 
COUNT (transaction_id) AS count_items,
COUNT (transaction_id)::NUMERIC/(
SELECT
COUNT (transaction_id)
FROM fantasy.events
WHERE amount<>0) AS item_share,
COUNT (DISTINCT id)::NUMERIC/(
SELECT
COUNT (DISTINCT id)
FROM fantasy.events
WHERE amount<>0) AS id_share
FROM fantasy.events AS e
LEFT JOIN fantasy.items AS i ON e.item_code=i.item_code
WHERE amount<>0
GROUP BY game_items
HAVING COUNT(transaction_id)>=1
ORDER BY id_share DESC

-- Часть 2. Решение ad hoc-задач
-- Задача 1. Зависимость активности игроков от расы персонажа:
SELECT
race,
COUNT(DISTINCT u.id) AS all_players,
COUNT(DISTINCT u.id) FILTER (WHERE amount>0) AS players_who_make_purchases,
COUNT(DISTINCT u.id) FILTER (WHERE amount>0)/COUNT(DISTINCT u.id)::numeric AS purchase_makers_share,
COUNT(DISTINCT u.id) FILTER (WHERE payer=1 AND amount>0)::numeric/COUNT(DISTINCT u.id) FILTER (WHERE amount>0) AS payers_share,
COUNT(transaction_id)/COUNT(DISTINCT u.id) FILTER (WHERE amount>0) AS avg_transaction,
SUM(amount)/COUNT(transaction_id) FILTER (WHERE amount>0) AS avg_purchase_per_id,
SUM(amount)/COUNT(DISTINCT u.id) FILTER (WHERE amount>0) AS avg_sum_purchase
FROM fantasy.events AS e
FULL JOIN fantasy.users AS u ON e.id=u.id
FULL JOIN fantasy.race AS r ON u.race_id=r.race_id
GROUP BY race
