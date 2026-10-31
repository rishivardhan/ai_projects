-- M0 seed: ten names whose Xetra line is the primary or a liquid secondary listing.
-- The full ~40-listing universe arrives in M1; edges and tickers stay data, not code.
INSERT INTO reference.company (id, name, tier, country, tradable) VALUES
    ('sap',            'SAP',                 'HYPERSCALER',         'DE', TRUE),
    ('deutsche-telekom','Deutsche Telekom',   'HYPERSCALER',         'DE', TRUE),
    ('infineon',       'Infineon Technologies','CHIP_DESIGNER',      'DE', TRUE),
    ('siltronic',      'Siltronic',           'FOUNDRY_MEMORY',      'DE', TRUE),
    ('aixtron',        'Aixtron',             'EQUIPMENT_MATERIALS', 'DE', TRUE),
    ('suss-microtec',  'SÜSS MicroTec',       'EQUIPMENT_MATERIALS', 'DE', TRUE),
    ('merck-kgaa',     'Merck KGaA',          'EQUIPMENT_MATERIALS', 'DE', TRUE),
    ('asml',           'ASML Holding',        'EQUIPMENT_MATERIALS', 'NL', TRUE),
    ('siemens-energy', 'Siemens Energy',      'POWER_INFRA',         'DE', TRUE),
    ('siemens',        'Siemens',             'POWER_INFRA',         'DE', TRUE);

INSERT INTO reference.listing (id, company_id, isin, mic, symbol, currency, source) VALUES
    ('DE0007164600@XETR', 'sap',              'DE0007164600', 'XETR', 'SAP',  'EUR', 'deutsche-boerse-detr'),
    ('DE0005557508@XETR', 'deutsche-telekom', 'DE0005557508', 'XETR', 'DTE',  'EUR', 'deutsche-boerse-detr'),
    ('DE0006231004@XETR', 'infineon',         'DE0006231004', 'XETR', 'IFX',  'EUR', 'deutsche-boerse-detr'),
    ('DE000WAF3001@XETR', 'siltronic',        'DE000WAF3001', 'XETR', 'WAF',  'EUR', 'deutsche-boerse-detr'),
    ('DE000A0WMPJ6@XETR', 'aixtron',          'DE000A0WMPJ6', 'XETR', 'AIXA', 'EUR', 'deutsche-boerse-detr'),
    ('DE000A1K0235@XETR', 'suss-microtec',    'DE000A1K0235', 'XETR', 'SMHN', 'EUR', 'deutsche-boerse-detr'),
    ('DE0006599905@XETR', 'merck-kgaa',       'DE0006599905', 'XETR', 'MRK',  'EUR', 'deutsche-boerse-detr'),
    ('NL0010273215@XETR', 'asml',             'NL0010273215', 'XETR', 'ASME', 'EUR', 'deutsche-boerse-detr'),
    ('DE000ENER6Y0@XETR', 'siemens-energy',   'DE000ENER6Y0', 'XETR', 'ENR',  'EUR', 'deutsche-boerse-detr'),
    ('DE0007236101@XETR', 'siemens',          'DE0007236101', 'XETR', 'SIE',  'EUR', 'deutsche-boerse-detr');
