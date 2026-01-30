# Contact and Business Management Feature Tests

This document summarizes the comprehensive test suite for the default contact functionality and business deletion features implemented in the contacts app.

## Default Contact Behavior

The default contact system follows these rules:

1. **Single Contact**: When a business has only one contact, that contact is automatically set as the default
2. **Multiple Contacts**: When a business has multiple contacts, the user must manually select which is default
3. **Deleting Default Contact**:
   - **Multiple contacts remaining (2+)**: User is shown a selection form and must choose a new default before deletion proceeds
   - **One contact remaining**: The remaining contact is automatically set as default
   - **No contacts remaining**: The default is cleared
4. **Moving Default Contact**: When a default contact is moved to another business:
   - Original business: Default is cleared (user must manually select new default if multiple contacts remain)
   - New business: Contact becomes default if it's the only contact
5. **Manual Selection**: Users can set any contact as default via:
   - Checkbox on "Add Business Contact" form
   - "Set as Default Contact" button on contact detail page
   - Selection form when deleting a default contact (if multiple contacts remain)

## Business Deletion Behavior

The business deletion system follows these rules:

1. **Validation**: A business cannot be deleted if any of its contacts are associated with Jobs or Bills
   - The system checks all contacts for associations before allowing deletion
   - If associations exist, an error message lists all affected contacts and their associations

2. **No Contacts**: If a business has no contacts, it can be deleted immediately without confirmation

3. **With Contacts (No Associations)**: If a business has contacts but none have Jobs/Bills associations:
   - User is shown a confirmation form with two action choices
   - **Unlink Action**: Contacts are kept in the system but become independent (business field set to null)
   - **Delete Action**: All contacts are permanently deleted along with the business

4. **User Choice Required**: When contacts exist, the user must explicitly select an action (unlink or delete) before the deletion proceeds

5. **UI Elements**:
   - Business detail page has a "Delete Business" button
   - JavaScript confirmation dialog warns user before showing confirmation form
   - Confirmation form displays all associated contacts for review

## Test Files Created

### 1. test_default_contact_functionality.py (12 tests)
Tests the automatic default contact management at the model level.

**Test Classes:**
- `DefaultContactAutomaticAssignmentTest` (4 tests)
  - Single contact auto-set as default
  - Adding second contact preserves default
  - Moving contact to business sets as default if only one
  - No default when no contacts exist

- `DefaultContactReassignmentTest` (3 tests)
  - Removing default contact clears default when no others
  - Removing non-default contact preserves default
  - Moving default contact to another business clears default (not auto-reassign)

- `DefaultContactUpdateMethodTest` (3 tests)
  - Update with one contact sets it as default
  - Update with no contacts clears default
  - Update with invalid default clears and reassigns appropriately

- `DefaultContactMultipleContactsTest` (2 tests)
  - Multiple contacts don't auto-change default
  - Default persists across business saves

### 2. test_set_default_contact_views.py (16 tests)
Tests the UI views for setting default contacts.

**Test Classes:**
- `AddBusinessContactWithDefaultTest` (4 tests)
  - Adding contact with checkbox sets as default
  - Adding without checkbox preserves existing default
  - First contact with checkbox becomes default
  - Validation errors don't affect default

- `SetDefaultContactViewTest` (6 tests)
  - POST request sets contact as default
  - Setting default for contact without business shows error
  - GET request redirects without changing default
  - Setting already-default contact works
  - Redirects to contact detail page
  - Contact without business has no error

- `ContactDetailPageDefaultIndicatorTest` (4 tests)
  - Default contact shows [DEFAULT CONTACT] badge
  - Non-default shows "Set as Default Contact" button
  - Default doesn't show set default button
  - Contact without business shows no default controls

- `BusinessDetailPageDefaultDisplayTest` (2 tests)
  - Business detail shows default contact
  - Default contact highlighted in contact list

### 3. test_delete_contact_functionality.py (18 tests)
Tests contact deletion with validation and required default selection.

**Test Classes:**
- `ContactDeletionValidationTest` (3 tests)
  - Cannot delete contact with Job
  - Cannot delete contact with Bill
  - Cannot delete contact with multiple associations

- `ContactDeletionSuccessTest` (5 tests)
  - Can delete contact with no associations
  - Can delete contact with business but no Jobs/Bills
  - Redirects to business detail when has business
  - Redirects to contact list when no business
  - GET request doesn't delete

- `DefaultContactReassignmentOnDeletionTest` (8 tests)
  - Deleting default with multiple contacts shows selection form
  - Deleting default with new default selected completes successfully
  - Deleting default with one remaining contact auto-assigns that contact
  - Deleting only contact clears default
  - Deleting non-default preserves default
  - Invalid selection shows error and prevents deletion
  - Success message shows which contact is now the default
  - Success message indicates no default when last contact deleted

- `ContactDetailPageDeleteButtonTest` (2 tests)
  - Contact detail has delete button
  - Delete button has JavaScript confirmation

### 4. test_delete_business_functionality.py (16 tests)
Tests business deletion with validation and contact action choices.

**Test Classes:**
- `BusinessDeletionValidationTest` (3 tests)
  - Cannot delete business when contact has Job
  - Cannot delete business when contact has Bill
  - Cannot delete business with multiple contact associations

- `BusinessDeletionConfirmationFormTest` (3 tests)
  - Confirmation form shown when business has contacts
  - Confirmation form shows contact count
  - No confirmation form when no contacts (immediate deletion)

- `BusinessDeletionUnlinkActionTest` (3 tests)
  - Unlink action keeps contacts but removes business association
  - Unlink action shows appropriate success message
  - Unlink action redirects to business list

- `BusinessDeletionDeleteActionTest` (3 tests)
  - Delete action removes business and all contacts
  - Delete action shows appropriate success message
  - Delete action redirects to business list

- `BusinessDeletionMissingActionTest` (1 test)
  - Missing action shows confirmation form, not process deletion

- `BusinessDetailPageDeleteButtonTest` (2 tests)
  - Business detail page has delete button
  - Delete button has JavaScript confirmation

- `BusinessDeletionGETRequestTest` (1 test)
  - GET request does not delete business

## Running the Tests

Run all contact and business feature tests:
```bash
python manage.py test tests.test_default_contact_functionality tests.test_set_default_contact_views tests.test_delete_contact_functionality tests.test_delete_business_functionality
```

Run specific test file:
```bash
python manage.py test tests.test_delete_business_functionality
```

Run specific test class:
```bash
python manage.py test tests.test_default_contact_functionality.DefaultContactAutomaticAssignmentTest
```

Run specific test:
```bash
python manage.py test tests.test_default_contact_functionality.DefaultContactAutomaticAssignmentTest.test_single_contact_auto_set_as_default
```

## Test Coverage

These tests cover:
- ✅ Automatic default contact assignment (when business has only one contact)
- ✅ Default contact preservation and updates
- ✅ Default contact clearing when removed
- ✅ Setting default via add business contact form
- ✅ Setting default via contact detail page button
- ✅ **Required default selection when deleting default contact (multiple contacts remaining)**
- ✅ **Selection form validation and error handling**
- ✅ **Auto-assignment when only one contact remains**
- ✅ UI display of default contact indicators
- ✅ Contact deletion validation (Jobs and Bills)
- ✅ **Business deletion validation (preventing deletion when contacts have Jobs/Bills)**
- ✅ **Business deletion with contact action choices (unlink vs delete)**
- ✅ **Confirmation forms for business deletion**
- ✅ **Unlink action (contacts become independent)**
- ✅ **Delete action (contacts deleted with business)**
- ✅ Proper redirects and success messages

## Test Results

All 62 tests pass successfully:
- 12 default contact functionality tests
- 16 set default contact views tests
- 18 delete contact functionality tests
- 16 delete business functionality tests

Total: **62 tests, 100% passing**
