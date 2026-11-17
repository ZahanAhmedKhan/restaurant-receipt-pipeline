-- 005_item_mapping.sql
-- Rules that turn messy receipt descriptions into standard items.
-- Editable: add a row for every new description (or use the Items page in the app).
--
-- description_pattern: like SQL ILIKE: % = any text, case doesn't matter.
--   '%CHKN%BRST%' matches 'CHKN BRST 10LB'. If several rules match, the longest pattern wins.
-- standard_unit: lb (weight), each (count) or L (volume). kg is converted to lb.
-- pack_size / pack_unit: optional. Leave empty to read the pack size from the
--   description (e.g. '10LB', '4.5KG', '115CT', '15DZ', '1GAL').

CREATE TABLE mart.item_mapping (
    mapping_id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    description_pattern  TEXT NOT NULL UNIQUE,
    item_name            TEXT NOT NULL,
    category             TEXT,
    standard_unit        TEXT NOT NULL CHECK (standard_unit IN ('lb', 'kg', 'each', 'L')),
    pack_size            NUMERIC(12, 3),
    pack_unit            TEXT CHECK (pack_unit IN ('LB', 'KG', 'OZ', 'CT', 'DZ', 'EA', 'GAL', 'L'))
);

-- Rules for the fake sample vendors' items
INSERT INTO mart.item_mapping (description_pattern, item_name, category, standard_unit) VALUES
    ('%CHKN%BRST%',        'chicken breast',     'Meat',     'lb'),
    ('%CHICKEN%BREAST%',   'chicken breast',     'Meat',     'lb'),
    ('%CHKN%THIGH%',       'chicken thigh',      'Meat',     'lb'),
    ('%GRND%BEEF%',        'ground beef 80/20',  'Meat',     'lb'),
    ('%GROUND%BEEF%',      'ground beef 80/20',  'Meat',     'lb'),
    ('%BEEF%BRISKET%',     'beef brisket',       'Meat',     'lb'),
    ('%LAMB%LEG%',         'lamb leg',           'Meat',     'lb'),
    ('%GOAT%CUBES%',       'goat cubes',         'Meat',     'lb'),
    ('%RICE%JASMINE%',     'jasmine rice',       'Dry goods','lb'),
    ('%OIL%CANOLA%',       'canola oil',         'Dry goods','lb'),
    ('%FLOUR%AP%',         'all-purpose flour',  'Dry goods','lb'),
    ('%EGGS%LG%',          'large eggs',         'Dairy',    'each'),
    ('%ONION%YEL%',        'yellow onions',      'Produce',  'lb'),
    ('%TOMATO%',           'tomatoes',           'Produce',  'lb'),
    ('%TOMATOES%ROMA%',    'roma tomatoes',      'Produce',  'lb'),
    ('%LETTUCE%ROMAINE%',  'romaine lettuce',    'Produce',  'each'),
    ('%POTATO%RUSSET%',    'russet potatoes',    'Produce',  'lb'),
    ('%CILANTRO%',         'cilantro bunches',   'Produce',  'each'),
    ('%LEMONS%',           'lemons',             'Produce',  'each'),
    ('%GARLIC%PEELED%',    'peeled garlic',      'Produce',  'lb'),
    ('%PEPPER%GREEN%BELL%','green bell peppers', 'Produce',  'lb'),
    ('%GLOVES%NITRILE%',   'nitrile gloves',     'Supplies', 'each'),
    ('%FOIL%ROLL%',        'foil roll 18in',     'Supplies', 'each'),
    ('%TO-GO%BOX%',        'to-go boxes 9x9',    'Supplies', 'each'),
    ('%NAPKINS%',          'napkins',            'Supplies', 'each'),
    ('%DISH%SOAP%',        'dish soap',          'Supplies', 'L');
