-- Three fake businesses with 3 contacts each, for testing deletion.
-- IDs 201-209 (contacts) and 201-203 (businesses) to avoid conflicts.
-- Run with: mysql -u <user> -p <database> < fixtures/solo-businesses-contacts.sql

-- Step 1: Contacts with NULL business (circular dependency)
INSERT INTO contacts (contact_id, first_name, middle_initial, last_name, email, mobile_number, work_number, home_number, addr1, addr2, addr3, city, municipality, postal_code, country_code, business_id)
VALUES
  (201, 'Alice',   '', 'Anvil',    'alice@acme.test',        '555-1001', '', '', '', '', '', '', '', '', '', NULL),
  (202, 'Bob',     '', 'Blast',    'bob@acme.test',          '555-1002', '', '', '', '', '', '', '', '', '', NULL),
  (203, 'Carol',   '', 'Crater',   'carol@acme.test',        '555-1003', '', '', '', '', '', '', '', '', '', NULL),
  (204, 'Dan',     '', 'Dummy',    'dan@placeholder.test',   '555-1004', '', '', '', '', '', '', '', '', '', NULL),
  (205, 'Eve',     '', 'Empty',    'eve@placeholder.test',   '555-1005', '', '', '', '', '', '', '', '', '', NULL),
  (206, 'Frank',   '', 'Filler',   'frank@placeholder.test', '555-1006', '', '', '', '', '', '', '', '', '', NULL),
  (207, 'Grace',   '', 'Gone',     'grace@temp.test',        '555-1007', '', '', '', '', '', '', '', '', '', NULL),
  (208, 'Hank',    '', 'History',  'hank@temp.test',         '555-1008', '', '', '', '', '', '', '', '', '', NULL),
  (209, 'Irene',   '', 'Interim',  'irene@temp.test',        '555-1009', '', '', '', '', '', '', '', '', '', NULL);

-- Step 2: Businesses pointing to their default contacts
INSERT INTO businesses (business_id, our_reference_code, business_name, business_address, business_phone, tax_exemption_number, website, default_contact_id)
VALUES
  (201, 'FAKE1', 'Acme Demolition',        '123 Boom St',     '555-0201', '', '', 201),
  (202, 'FAKE2', 'Placeholder Industries',  '456 Null Ave',    '555-0202', '', '', 204),
  (203, 'FAKE3', 'Temp Corp',               '789 Delete Blvd', '555-0203', '', '', 207);

-- Step 3: Link contacts to their businesses
UPDATE contacts SET business_id = 201 WHERE contact_id IN (201, 202, 203);
UPDATE contacts SET business_id = 202 WHERE contact_id IN (204, 205, 206);
UPDATE contacts SET business_id = 203 WHERE contact_id IN (207, 208, 209);
