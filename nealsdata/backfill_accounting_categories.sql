-- Backfill accounting_category on price_list items by code.
-- Uses subquery to look up category by code, so PKs don't matter.

-- Service (SVC): 9 items
UPDATE price_list
SET accounting_category_id = (SELECT id FROM accounting_categories WHERE code = 'SVC')
WHERE code IN (
    '1 estimate',
    '1 rough estimate',
    '2 SETUP',
    '4 PROV',
    '5 CAD',
    '6 FINISH',
    '8 MIN',
    '9 CONSULT',
    'CRATE'
);

-- Material (MTL): 94 items
UPDATE price_list
SET accounting_category_id = (SELECT id FROM accounting_categories WHERE code = 'MTL')
WHERE code IN (
    '3 AXYZ',
    '3 KOMO',
    '3 LASER',
    '3 MM',
    'ABS.125',
    'ACM.125',
    'ACR.125',
    'ACR.25',
    'ACR.5',
    'ACR.75',
    'ACX.375',
    'ACX.5',
    'ACX.625',
    'ACX.75',
    'ALU.05-4x12',
    'ALU.125',
    'ALU.125-5x12',
    'APPLY.5',
    'APPLY.5P',
    'APPLY.75P',
    'APPLY1.0',
    'BBPLY.125-5x5',
    'BBPLY.25',
    'BBPLY.25-5x5',
    'BBPLY.375',
    'BBPLY.5',
    'BBPLY.5-5x5',
    'BBPLY.5-5x5P',
    'BBPLY.5BBB',
    'BBPLY.5P',
    'BBPLY.625',
    'BBPLY.625P-5X5',
    'BBPLY.75',
    'BBPLY.75-5x10',
    'BBPLY.75-5x5',
    'BBPLY.75P',
    'BBPLY1.0',
    'HDPE.375',
    'HDPE.5',
    'HDPE.75',
    'HDU1.0',
    'IMPLY.25',
    'IMPLY.5',
    'IMPLY.58',
    'IMPLY.5P',
    'IMPLY.75',
    'IMPLY.75P',
    'IMPLY1',
    'LAUAN.25',
    'MAPLY.25',
    'MAPLY.25P',
    'MAPLY.5P',
    'MAPLY.75',
    'MAPLY.75P',
    'MAPLY.75P1S',
    'MAPLY1.0',
    'MAR.5',
    'MAR.75',
    'MAR1.0',
    'MARO.75',
    'MDF.125',
    'MDF.25',
    'MDF.375',
    'MDF.5',
    'MDF.625',
    'MDF.75',
    'MDF.75-4X10',
    'MDF.75-5x10',
    'MDF.75-5x8',
    'MDF.75U',
    'MDF1.0',
    'MDFUL.5',
    'MDFUL.75',
    'MEL.75-5X8',
    'PLYBOO.5',
    'PLYBOO.75',
    'PLYBOO1.0',
    'POLY.125',
    'POLY.25',
    'POLY.50',
    'PVC .25',
    'PVC.125',
    'PVC.5',
    'R1-oil',
    'SHOPB.5',
    'SHOPB.75',
    'SHOPB.75P',
    'SHOPM.5P',
    'SHOPM.75',
    'SHOPM.75P',
    'TIG.75',
    'WAL.5',
    'WIG.25',
    'WOAK.75'
);

-- Product (PRD): 25 items
UPDATE price_list
SET accounting_category_id = (SELECT id FROM accounting_categories WHERE code = 'PRD')
WHERE code IN (
    'ARZABE',
    'BAU1',
    'BAU2',
    'EDGE1',
    'GLAMP',
    'GLPVAN',
    'HIVE- 1-5',
    'HIVE- 6+',
    'IR-mat''l',
    'IR-palletize',
    'IR-POSv2',
    'IR-sign',
    'M67-full',
    'PM-4x8.75',
    'PM-5x10.75',
    'R1S-BED',
    'R1S-KIT',
    'R1T-KIT',
    'R1T-KIT-M',
    'R1T-SLD',
    'R1T-SLD-M',
    'R1T-STB',
    'R1T-STB-05M',
    'WESTERNDRILL',
    'WESTERNLF8mm'
);

-- Delivery (DLV): 5 items
UPDATE price_list
SET accounting_category_id = (SELECT id FROM accounting_categories WHERE code = 'DLV')
WHERE code IN (
    '7 DELIVERY',
    '7 DELIVERY PEN',
    '7 DELIVERY SF',
    '7 DELIVERY SF car',
    '7 DELIVERY SF lg'
);

-- Safety: set any remaining NULL items to Material
UPDATE price_list
SET accounting_category_id = (SELECT id FROM accounting_categories WHERE code = 'MTL')
WHERE accounting_category_id IS NULL;
