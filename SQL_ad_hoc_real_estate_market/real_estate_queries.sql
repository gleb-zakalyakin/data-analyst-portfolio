WITH limits AS (
    SELECT  
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY total_area) AS total_area_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY rooms) AS rooms_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY balcony) AS balcony_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY ceiling_height) AS ceiling_height_limit_h,
        PERCENTILE_DISC(0.01) WITHIN GROUP (ORDER BY ceiling_height) AS ceiling_height_limit_l
    FROM real_estate.flats     
),
filtered_id AS(
    SELECT id
    FROM real_estate.flats  
    WHERE 
        total_area < (SELECT total_area_limit FROM limits)
        AND (rooms < (SELECT rooms_limit FROM limits) OR rooms IS NULL)
        AND (balcony < (SELECT balcony_limit FROM limits) OR balcony IS NULL)
        AND ((ceiling_height < (SELECT ceiling_height_limit_h FROM limits)
            AND ceiling_height > (SELECT ceiling_height_limit_l FROM limits)) OR ceiling_height IS NULL)
    ),
--title: Запрос 1.1    
First_task AS(
    SELECT f.id AS id_flats,
    a.last_price/f.total_area AS price_meter,
    total_area,
    ceiling_height,
    rooms,
    balcony,
    floor,
    CASE
       WHEN city_id = '6X8I'
    	  THEN 'Санкт-Петербург'
    	WHEN city_id <> '6x8I'
    	  THEN 'ЛенОбл'	  
    END AS region,
      CASE
      	WHEN days_exposition BETWEEN '1' AND '30'
      	 THEN 'Месяц'
      	  WHEN days_exposition BETWEEN '31' AND '90'
      	   THEN 'Квартал'
      	    WHEN days_exposition BETWEEN '91' AND '180'
      	     THEN 'Полгода'
      	      ELSE 'Более полугода'
    END AS period
    FROM real_estate.advertisement AS a
    INNER JOIN real_estate.flats AS f ON a.id=f.id
    INNER JOIN real_estate.type AS t ON f.type_id=t.type_id
    WHERE type = 'город' AND days_exposition IS NOT NULL AND f.id IN (SELECT * FROM filtered_id))
    --title: Запрос 1.2  
    SELECT
    region,
    period,
    COUNT(id_flats) AS id_amount,
    ROUND(COUNT(id_flats)/(SELECT COUNT(id_flats) FROM first_task)::numeric,2) AS id_share,
    ROUND(AVG(price_meter)::numeric,2) AS avg_price_meter,
    ROUND(AVG(total_area)::numeric,2) AS avg_total_area,
    ROUND(AVG(ceiling_height)::numeric,2) as avg_ceiling_height,
    PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY rooms) AS med_rooms,
    PERCENTILE_DISC(0.5) within group (ORDER BY balcony) AS med_balcony,
    PERCENTILE_DISC(0.5) within group (ORDER BY floor) AS med_floor
    FROM first_task 
    GROUP BY region, period;
WITH limits AS (
    SELECT  
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY total_area) AS total_area_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY rooms) AS rooms_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY balcony) AS balcony_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY ceiling_height) AS ceiling_height_limit_h,
        PERCENTILE_DISC(0.01) WITHIN GROUP (ORDER BY ceiling_height) AS ceiling_height_limit_l
    FROM real_estate.flats     
),
filtered_id AS(
    SELECT id
    FROM real_estate.flats  
    WHERE 
        total_area < (SELECT total_area_limit FROM limits)
        AND (rooms < (SELECT rooms_limit FROM limits) OR rooms IS NULL)
        AND (balcony < (SELECT balcony_limit FROM limits) OR balcony IS NULL)
        AND ((ceiling_height < (SELECT ceiling_height_limit_h FROM limits)
            AND ceiling_height > (SELECT ceiling_height_limit_l FROM limits)) OR ceiling_height IS NULL)
    ),
--title: Запрос 2.1      
TASK_2 AS(
    SELECT
    rea.id AS id_1,
    last_price,
    total_area, 
    last_price/total_area AS price_meter,
    EXTRACT (MONTH FROM first_day_exposition) AS id_appearance_month,
    EXTRACT (MONTH FROM first_day_exposition + days_exposition::integer) AS id_deleted_month
    FROM real_estate.advertisement AS rea
    INNER JOIN real_estate.flats AS ref ON rea.id=ref.id
    inner join real_estate.type as t on ref.type_id=t.type_id
    WHERE rea.id in (SELECT * FROM filtered_id) and type='город'),
--title: Запрос 2.2  
TASK_2_1 AS (
    SELECT
    id_appearance_month, 
    id_deleted_month,
    price_meter,
    total_area,
    COUNT(id_1) OVER (PARTITION BY id_appearance_month ORDER BY id_appearance_month) AS count_first_app,
    COUNT(id_1) OVER (PARTITION BY id_deleted_month ORDER BY id_deleted_month) AS count_sold
    FROM TASK_2),
--title: Запрос 2.3      
TASK_2_2 as (
    select 
    id_appearance_month,
    ROUND(AVG(price_meter)::numeric,2) AS avg_price_meter_app,
    ROUND(AVG(total_area)::numeric,2) AS avg_total_area_app
    from TASK_2_1 
    group by id_appearance_month),
--title: Запрос 2.4      
TASK_2_3 as (
    SELECT 
    id_deleted_month,
    ROUND(AVG(price_meter)::numeric,2) AS avg_price_meter_del,
    ROUND(AVG(total_area)::numeric,2) AS avg_total_area_del
    FROM TASK_2_1 
    GROUP BY id_deleted_month)
--title: Запрос 2.5       
    SELECT 
    id_appearance_month, 
    id_deleted_month,
    count_first_app,
    count_sold,
    avg_price_meter_app,
    avg_total_area_app,
    avg_price_meter_del,
    avg_total_area_del
FROM TASK_2_1 JOIN TASK_2_2 USING (id_appearance_month)  JOIN TASK_2_3 USING (id_deleted_month) 
WHERE id_appearance_month=id_deleted_month
GROUP BY id_appearance_month, id_deleted_month, count_first_app, count_sold, avg_price_meter_app, avg_total_area_app, avg_price_meter_del, avg_total_area_del;
WITH limits AS (
    SELECT  
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY total_area) AS total_area_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY rooms) AS rooms_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY balcony) AS balcony_limit,
        PERCENTILE_DISC(0.99) WITHIN GROUP (ORDER BY ceiling_height) AS ceiling_height_limit_h,
        PERCENTILE_DISC(0.01) WITHIN GROUP (ORDER BY ceiling_height) AS ceiling_height_limit_l
    FROM real_estate.flats     
),
filtered_id AS(
    SELECT id
    FROM real_estate.flats  
    WHERE 
        total_area < (SELECT total_area_limit FROM limits)
        AND (rooms < (SELECT rooms_limit FROM limits) OR rooms IS NULL)
        AND (balcony < (SELECT balcony_limit FROM limits) OR balcony IS NULL)
        AND ((ceiling_height < (SELECT ceiling_height_limit_h FROM limits)
            AND ceiling_height > (SELECT ceiling_height_limit_l FROM limits)) OR ceiling_height IS NULL)
    )
--title: Запрос 3      
SELECT 
city,
COUNT(f.id) AS all_id, 
Count(f.id) FILTER (WHERE days_exposition IS NOT NULL) AS sold_absolute,
ROUND(Count(f.id) FILTER (WHERE days_exposition IS NOT NULL)/COUNT(f.id)::numeric,2) AS sold_share,
ROUND(AVG(total_area)::numeric,2) as avg_ttl_area,
ROUND(AVG(last_price/total_area)::numeric,2) AS avg_price_meter,
ROUND(AVG(days_exposition)::numeric,2) AS avg_id_duration
FROM real_estate.advertisement AS a
INNER JOIN real_estate.flats AS f ON a.id=f.id
INNER JOIN real_estate.city AS C ON f.city_id=c.city_id
where city <> 'Санкт-Петербург' AND f.id IN (SELECT * FROM filtered_id)
GROUP BY city
ORDER BY Count(f.id) DESC 
LIMIT 15;