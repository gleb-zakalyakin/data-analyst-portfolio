# Анализ паттернов поведения пользователей «Яндекс Книги» (ClickHouse)

## Описание проекта
В рамках данного проекта выполнялся пул ad hoc задач от продакт-менеджера сервиса «Яндекс Книги». Основная цель исследования — анализ метрик потребления контента и паттернов использования сервиса на мобильных платформах «Букмейт iOS» и «Букмейт Android». Проект решает задачи продуктовой аналитики: сегментация пользователей по предпочтениям, оценка популярности контента и контроль актуальных версий установленных мобильных приложений.

## Стек и инструменты
- **База данных:** ClickHouse.
- **Инструменты:** SQL, Jupyter Notebook.
- **Ключевые функции SQL:** Обобщенные табличные выражения (CTE), специфичные аналитические агрегации ClickHouse (`sumIf`, `avgIf`, `uniqExact`, `argMax`), условная логика `multiIf` и оконные функции.

## Исходные данные
Анализ проводился на основе двух таблиц данных сервиса:
- `source_db.audition`: логи сессий пользователей, включающие информацию о длительности взаимодействия, гео-позиции, платформе и версии приложения.
- `source_db.content`: метаданные справочника контента, такие как название книги, автор, тип контента (Book/Audiobook) и категории.

## Ключевые бизнес-выводы
- **Сегментация платформ:** На платформе Android суммарное время использования сервиса более чем в 2 раза превышает показатели iOS (на примере московского региона: 18,5 тыс. часов против 8 тыс. часов).
- **Паттерны потребления:** Доли «слушателей» аудиокниг и «читателей» текста на Android распределены практически поровну (2 145 и 2 382 пользователя соответственно), тогда как на iOS преобладают текстовые читатели. Использование аудиокниг незначительно снижается в выходные дни на всех платформах.
- **Технические метрики обновления:** Выявлена проблема с регулярностью обновлений у пользователей iOS — актуальная версия установлена лишь у 1.91% аудитории. На платформе Android ситуация лучше: последней версией пользуются 28.92% клиентов, и частота обновлений там выше.
- **Предпочтения контента:** Самой популярной книгой является биография «Илон Маск» (суммарно более 1 012 часов прослушивания и чтения), а лидером по общей длительности потребления контента среди авторов стал Сергей Лукьяненко.

## Пример SQL-кода: Сегментация аудитории
Фрагмент запроса, определяющий основную платформу пользователя и его принадлежность к продуктовому сегменту («Слушатель», «Читатель» или «Оба») с использованием логических функций `multiIf` и агрегации `argMax`:

```sql
WITH platform_stats AS (
    SELECT puid,
           usage_platform_ru,
           sumIf(hours, main_content_type = 'Book') AS text_hours,
           sumIf(hours, main_content_type = 'Audiobook') AS audio_hours,
           sum(hours) AS platform_hours
    FROM source_db.audition
    INNER JOIN source_db.content USING (main_content_id)
    WHERE usage_platform_ru ILIKE '%Букмейт Android%' OR usage_platform_ru ILIKE '%Букмейт iOS%'
    GROUP BY puid, usage_platform_ru
),
user_aggregated AS (
    SELECT puid,
           argMax(usage_platform_ru, platform_hours) AS raw_main_platform,
           sum(text_hours) AS text_hours,
           sum(audio_hours) AS audio_hours,
           text_hours + audio_hours AS content_hours
    FROM platform_stats
    GROUP BY puid
    HAVING content_hours > 0
)
SELECT multiIf(
        raw_main_platform ILIKE '%Android%', 'Android',
        raw_main_platform ILIKE '%iOS%', 'iOS','Другое') AS main_platform,
       multiIf(
        audio_hours / content_hours >= 0.7, 'Слушатель',
        text_hours / content_hours >= 0.7, 'Читатель', 'Оба') AS segment,
       count() AS user_count
FROM user_aggregated
GROUP BY main_platform, segment
ORDER BY main_platform, user_count DESC
```
