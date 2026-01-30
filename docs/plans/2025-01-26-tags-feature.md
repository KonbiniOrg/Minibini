# Tags Feature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add free-form tagging to Jobs, Contacts, and Businesses so users can mark entities with labels like "blacklisted", "friend rate", "advance payment required".

**Architecture:** Normalized Tag model in core app with M2M relationships via through tables. Tags displayed wherever entities appear using prefetch_related for efficiency. Autocomplete via HTML5 datalist (no JS framework).

**Tech Stack:** Django models, M2M relationships, prefetch_related, HTML5 datalist for autocomplete

---

## Task 1: Create Tag Model

**Files:**
- Modify: `apps/core/models.py`
- Test: `tests/test_tag_models.py`

**Step 1: Write the failing test**

Create `tests/test_tag_models.py`:

```python
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.core.models import Tag


class TagModelTest(TestCase):
    def test_tag_creation(self):
        tag = Tag.objects.create(name="blacklisted")
        self.assertEqual(tag.name, "blacklisted")
        self.assertEqual(str(tag), "blacklisted")

    def test_tag_name_unique(self):
        Tag.objects.create(name="friend rate")
        with self.assertRaises(Exception):
            Tag.objects.create(name="friend rate")

    def test_tag_name_normalized(self):
        """Tags should be stored lowercase and trimmed"""
        tag = Tag.objects.create(name="  IMPORTANT  ")
        self.assertEqual(tag.name, "important")

    def test_tag_name_required(self):
        with self.assertRaises(ValidationError):
            tag = Tag(name="")
            tag.full_clean()
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_models -v 2`
Expected: FAIL with "cannot import name 'Tag'"

**Step 3: Write minimal implementation**

Add to `apps/core/models.py` after the Configuration class:

```python
class Tag(models.Model):
    """
    Free-form tags that can be applied to Jobs, Contacts, and Businesses.
    Used for labels like "blacklisted", "friend rate", "advance payment required".
    """
    tag_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def clean(self):
        if not self.name or not self.name.strip():
            raise ValidationError("Tag name is required.")

    def save(self, *args, **kwargs):
        # Normalize: lowercase and trim whitespace
        if self.name:
            self.name = self.name.strip().lower()
        self.full_clean()
        super().save(*args, **kwargs)
```

**Step 4: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_models -v 2`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add apps/core/models.py tests/test_tag_models.py
git commit -m "feat: add Tag model to core app"
```

---

## Task 2: Add Tags M2M to Contact Model

**Files:**
- Modify: `apps/contacts/models.py`
- Test: `tests/test_tag_models.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_models.py`:

```python
from apps.contacts.models import Contact, Business


class ContactTagTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            mobile_number="555-1234"
        )
        self.tag1 = Tag.objects.create(name="friend rate")
        self.tag2 = Tag.objects.create(name="vip")

    def test_add_tag_to_contact(self):
        self.contact.tags.add(self.tag1)
        self.assertIn(self.tag1, self.contact.tags.all())

    def test_contact_multiple_tags(self):
        self.contact.tags.add(self.tag1, self.tag2)
        self.assertEqual(self.contact.tags.count(), 2)

    def test_remove_tag_from_contact(self):
        self.contact.tags.add(self.tag1)
        self.contact.tags.remove(self.tag1)
        self.assertEqual(self.contact.tags.count(), 0)

    def test_tag_shared_across_contacts(self):
        contact2 = Contact.objects.create(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            mobile_number="555-5678"
        )
        self.contact.tags.add(self.tag1)
        contact2.tags.add(self.tag1)
        self.assertEqual(self.tag1.contacts.count(), 2)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_models.ContactTagTest -v 2`
Expected: FAIL with "Contact has no attribute 'tags'"

**Step 3: Write minimal implementation**

Add to `apps/contacts/models.py` in the Contact model (after the `business` field):

```python
    tags = models.ManyToManyField(
        'core.Tag',
        blank=True,
        related_name='contacts'
    )
```

**Step 4: Create migration**

Run: `python manage.py makemigrations contacts`
Expected: Creates migration adding tags field to Contact

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_models.ContactTagTest -v 2`
Expected: PASS (4 tests)

**Step 6: Commit**

```bash
git add apps/contacts/models.py apps/contacts/migrations/ tests/test_tag_models.py
git commit -m "feat: add tags M2M relationship to Contact model"
```

---

## Task 3: Add Tags M2M to Business Model

**Files:**
- Modify: `apps/contacts/models.py`
- Test: `tests/test_tag_models.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_models.py`:

```python
class BusinessTagTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name="Default",
            last_name="Contact",
            email="default@example.com",
            mobile_number="555-0000"
        )
        self.business = Business.objects.create(
            business_name="Acme Corp",
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()
        self.tag1 = Tag.objects.create(name="advance payment")
        self.tag2 = Tag.objects.create(name="slow payer")

    def test_add_tag_to_business(self):
        self.business.tags.add(self.tag1)
        self.assertIn(self.tag1, self.business.tags.all())

    def test_business_multiple_tags(self):
        self.business.tags.add(self.tag1, self.tag2)
        self.assertEqual(self.business.tags.count(), 2)

    def test_tag_shared_across_businesses(self):
        contact2 = Contact.objects.create(
            first_name="Other",
            last_name="Contact",
            email="other@example.com",
            mobile_number="555-9999"
        )
        business2 = Business.objects.create(
            business_name="Other Corp",
            default_contact=contact2
        )
        contact2.business = business2
        contact2.save()
        self.business.tags.add(self.tag1)
        business2.tags.add(self.tag1)
        self.assertEqual(self.tag1.businesses.count(), 2)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_models.BusinessTagTest -v 2`
Expected: FAIL with "Business has no attribute 'tags'"

**Step 3: Write minimal implementation**

Add to `apps/contacts/models.py` in the Business model (after the `default_contact` field):

```python
    tags = models.ManyToManyField(
        'core.Tag',
        blank=True,
        related_name='businesses'
    )
```

**Step 4: Create migration**

Run: `python manage.py makemigrations contacts`
Expected: Creates migration adding tags field to Business

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_models.BusinessTagTest -v 2`
Expected: PASS (3 tests)

**Step 6: Commit**

```bash
git add apps/contacts/models.py apps/contacts/migrations/ tests/test_tag_models.py
git commit -m "feat: add tags M2M relationship to Business model"
```

---

## Task 4: Add Tags M2M to Job Model

**Files:**
- Modify: `apps/jobs/models.py`
- Test: `tests/test_tag_models.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_models.py`:

```python
from apps.jobs.models import Job


class JobTagTest(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name="Customer",
            last_name="One",
            email="customer@example.com",
            mobile_number="555-1111"
        )
        self.job = Job.objects.create(
            job_number="JOB-001",
            contact=self.contact
        )
        self.tag1 = Tag.objects.create(name="job to copy")
        self.tag2 = Tag.objects.create(name="reference")

    def test_add_tag_to_job(self):
        self.job.tags.add(self.tag1)
        self.assertIn(self.tag1, self.job.tags.all())

    def test_job_multiple_tags(self):
        self.job.tags.add(self.tag1, self.tag2)
        self.assertEqual(self.job.tags.count(), 2)

    def test_tag_shared_across_jobs(self):
        job2 = Job.objects.create(
            job_number="JOB-002",
            contact=self.contact
        )
        self.job.tags.add(self.tag1)
        job2.tags.add(self.tag1)
        self.assertEqual(self.tag1.jobs.count(), 2)
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_models.JobTagTest -v 2`
Expected: FAIL with "Job has no attribute 'tags'"

**Step 3: Write minimal implementation**

Add to `apps/jobs/models.py` in the Job model (after the `description` field):

```python
    tags = models.ManyToManyField(
        'core.Tag',
        blank=True,
        related_name='jobs'
    )
```

**Step 4: Create migration**

Run: `python manage.py makemigrations jobs`
Expected: Creates migration adding tags field to Job

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_models.JobTagTest -v 2`
Expected: PASS (3 tests)

**Step 6: Commit**

```bash
git add apps/jobs/models.py apps/jobs/migrations/ tests/test_tag_models.py
git commit -m "feat: add tags M2M relationship to Job model"
```

---

## Task 5: Create Core Migration for Tag Model

**Files:**
- Create: `apps/core/migrations/` (new migration)

**Step 1: Create migration**

Run: `python manage.py makemigrations core`
Expected: Creates migration for Tag model

**Step 2: Verify all migrations work together**

Run: `python manage.py test tests.test_tag_models -v 2`
Expected: All tag tests PASS (14 tests total)

**Step 3: Commit**

```bash
git add apps/core/migrations/
git commit -m "chore: add migration for Tag model"
```

---

## Task 6: Create Tag Display Template Include

**Files:**
- Create: `templates/includes/tag_display.html`
- Test: Manual verification

**Step 1: Create the template include**

Create `templates/includes/tag_display.html`:

```html
{% if tags %}
<p>
    <strong>Tags:</strong>
    {% for tag in tags %}
        <span style="background-color: #e0e0e0; padding: 2px 8px; margin-right: 4px; border-radius: 3px;">{{ tag.name }}</span>
    {% endfor %}
</p>
{% endif %}
```

**Step 2: Commit**

```bash
git add templates/includes/tag_display.html
git commit -m "feat: add tag display template include"
```

---

## Task 7: Add Tags to Contact Detail View

**Files:**
- Modify: `apps/contacts/views.py`
- Modify: `templates/contacts/contact_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing test**

Create `tests/test_tag_views.py`:

```python
from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.core.models import Tag


class ContactTagDisplayTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            mobile_number="555-1234"
        )
        self.tag = Tag.objects.create(name="vip customer")
        self.contact.tags.add(self.tag)

    def test_contact_detail_shows_tags(self):
        response = self.client.get(
            reverse('contacts:contact_detail', args=[self.contact.contact_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "vip customer")
        self.assertContains(response, "Tags:")
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_views.ContactTagDisplayTest -v 2`
Expected: FAIL with "Tags:" not found in response

**Step 3: Update view to prefetch tags**

Modify `apps/contacts/views.py` `contact_detail` function:

```python
def contact_detail(request, contact_id):
    contact = get_object_or_404(
        Contact.objects.prefetch_related('tags'),
        contact_id=contact_id
    )
    return render(request, 'contacts/contact_detail.html', {'contact': contact})
```

**Step 4: Update template to display tags**

Add to `templates/contacts/contact_detail.html` after the closing `</table>` tag (around line 66):

```html
{% include 'includes/tag_display.html' with tags=contact.tags.all %}
```

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_views.ContactTagDisplayTest -v 2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/contacts/views.py templates/contacts/contact_detail.html tests/test_tag_views.py
git commit -m "feat: display tags on contact detail page"
```

---

## Task 8: Add Tags to Business Detail View

**Files:**
- Modify: `apps/contacts/views.py`
- Modify: `templates/contacts/business_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_views.py`:

```python
class BusinessTagDisplayTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Default",
            last_name="Contact",
            email="default@example.com",
            mobile_number="555-0000"
        )
        self.business = Business.objects.create(
            business_name="Acme Corp",
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()
        self.tag = Tag.objects.create(name="advance payment required")
        self.business.tags.add(self.tag)

    def test_business_detail_shows_tags(self):
        response = self.client.get(
            reverse('contacts:business_detail', args=[self.business.business_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "advance payment required")
        self.assertContains(response, "Tags:")
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_views.BusinessTagDisplayTest -v 2`
Expected: FAIL with "Tags:" not found in response

**Step 3: Update view to prefetch tags**

Modify `apps/contacts/views.py` `business_detail` function:

```python
def business_detail(request, business_id):
    business = get_object_or_404(
        Business.objects.prefetch_related('tags'),
        business_id=business_id
    )
    contacts = Contact.objects.filter(business=business).order_by('last_name', 'first_name')
    return render(request, 'contacts/business_detail.html', {'business': business, 'contacts': contacts})
```

**Step 4: Update template to display tags**

First read current business_detail.html to find right location, then add after the business info table:

```html
{% include 'includes/tag_display.html' with tags=business.tags.all %}
```

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_views.BusinessTagDisplayTest -v 2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/contacts/views.py templates/contacts/business_detail.html tests/test_tag_views.py
git commit -m "feat: display tags on business detail page"
```

---

## Task 9: Add Tags to Job Detail View

**Files:**
- Modify: `apps/jobs/views.py`
- Modify: `templates/jobs/job_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_views.py`:

```python
from apps.jobs.models import Job


class JobTagDisplayTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Customer",
            last_name="One",
            email="customer@example.com",
            mobile_number="555-1111"
        )
        self.job = Job.objects.create(
            job_number="JOB-TEST-001",
            contact=self.contact
        )
        self.tag = Tag.objects.create(name="job to copy")
        self.job.tags.add(self.tag)

    def test_job_detail_shows_tags(self):
        response = self.client.get(
            reverse('jobs:detail', args=[self.job.job_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "job to copy")
        self.assertContains(response, "Tags:")
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_views.JobTagDisplayTest -v 2`
Expected: FAIL with "Tags:" not found in response

**Step 3: Update view to prefetch tags**

Find and modify the job detail view in `apps/jobs/views.py` to use prefetch_related for tags:

```python
job = get_object_or_404(
    Job.objects.prefetch_related('tags'),
    job_id=job_id
)
```

**Step 4: Update template to display tags**

Add to `templates/jobs/job_detail.html` after the job info section:

```html
{% include 'includes/tag_display.html' with tags=job.tags.all %}
```

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_views.JobTagDisplayTest -v 2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/jobs/views.py templates/jobs/job_detail.html tests/test_tag_views.py
git commit -m "feat: display tags on job detail page"
```

---

## Task 10: Create Add Tag View for Contact

**Files:**
- Modify: `apps/contacts/views.py`
- Modify: `apps/contacts/urls.py`
- Modify: `templates/contacts/contact_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_views.py`:

```python
class AddTagToContactTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            mobile_number="555-1234"
        )

    def test_add_new_tag_to_contact(self):
        response = self.client.post(
            reverse('contacts:add_tag', args=[self.contact.contact_id]),
            {'tag_name': 'new tag'}
        )
        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.tags.count(), 1)
        self.assertEqual(self.contact.tags.first().name, 'new tag')

    def test_add_existing_tag_to_contact(self):
        tag = Tag.objects.create(name='existing tag')
        response = self.client.post(
            reverse('contacts:add_tag', args=[self.contact.contact_id]),
            {'tag_name': 'existing tag'}
        )
        self.assertEqual(response.status_code, 302)
        self.contact.refresh_from_db()
        self.assertIn(tag, self.contact.tags.all())

    def test_add_tag_normalizes_name(self):
        response = self.client.post(
            reverse('contacts:add_tag', args=[self.contact.contact_id]),
            {'tag_name': '  VIP Customer  '}
        )
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.tags.first().name, 'vip customer')
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_views.AddTagToContactTest -v 2`
Expected: FAIL with NoReverseMatch for 'contacts:add_tag'

**Step 3: Add URL pattern**

Add to `apps/contacts/urls.py`:

```python
    path('<int:contact_id>/add-tag/', views.add_tag_to_contact, name='add_tag'),
```

**Step 4: Add view function**

Add to `apps/contacts/views.py`:

```python
from apps.core.models import Tag

def add_tag_to_contact(request, contact_id):
    contact = get_object_or_404(Contact, contact_id=contact_id)

    if request.method == 'POST':
        tag_name = request.POST.get('tag_name', '').strip().lower()
        if tag_name:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            contact.tags.add(tag)
            messages.success(request, f'Tag "{tag.name}" added to {contact.name}.')
        else:
            messages.error(request, 'Tag name is required.')

    return redirect('contacts:contact_detail', contact_id=contact_id)
```

**Step 5: Add form to contact detail template**

Add to `templates/contacts/contact_detail.html` after the tag display include:

```html
<h3>Add Tag</h3>
<form method="post" action="{% url 'contacts:add_tag' contact.contact_id %}">
    {% csrf_token %}
    <p>
        <input type="text" name="tag_name" list="existing-tags" placeholder="Enter tag name">
        <datalist id="existing-tags">
            {% for tag in all_tags %}
                <option value="{{ tag.name }}">
            {% endfor %}
        </datalist>
        <button type="submit">Add Tag</button>
    </p>
</form>
```

**Step 6: Update view to pass all_tags to template**

Update `contact_detail` view:

```python
def contact_detail(request, contact_id):
    contact = get_object_or_404(
        Contact.objects.prefetch_related('tags'),
        contact_id=contact_id
    )
    all_tags = Tag.objects.all()
    return render(request, 'contacts/contact_detail.html', {
        'contact': contact,
        'all_tags': all_tags
    })
```

**Step 7: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_views.AddTagToContactTest -v 2`
Expected: PASS (3 tests)

**Step 8: Commit**

```bash
git add apps/contacts/views.py apps/contacts/urls.py templates/contacts/contact_detail.html tests/test_tag_views.py
git commit -m "feat: add tag functionality for contacts with autocomplete"
```

---

## Task 11: Create Remove Tag View for Contact

**Files:**
- Modify: `apps/contacts/views.py`
- Modify: `apps/contacts/urls.py`
- Modify: `templates/contacts/contact_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_views.py`:

```python
class RemoveTagFromContactTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            mobile_number="555-1234"
        )
        self.tag = Tag.objects.create(name="to remove")
        self.contact.tags.add(self.tag)

    def test_remove_tag_from_contact(self):
        response = self.client.post(
            reverse('contacts:remove_tag', args=[self.contact.contact_id, self.tag.tag_id])
        )
        self.assertEqual(response.status_code, 302)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.tags.count(), 0)

    def test_tag_not_deleted_when_removed(self):
        """Removing tag from contact should not delete the tag itself"""
        response = self.client.post(
            reverse('contacts:remove_tag', args=[self.contact.contact_id, self.tag.tag_id])
        )
        self.assertTrue(Tag.objects.filter(tag_id=self.tag.tag_id).exists())
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_views.RemoveTagFromContactTest -v 2`
Expected: FAIL with NoReverseMatch for 'contacts:remove_tag'

**Step 3: Add URL pattern**

Add to `apps/contacts/urls.py`:

```python
    path('<int:contact_id>/remove-tag/<int:tag_id>/', views.remove_tag_from_contact, name='remove_tag'),
```

**Step 4: Add view function**

Add to `apps/contacts/views.py`:

```python
def remove_tag_from_contact(request, contact_id, tag_id):
    contact = get_object_or_404(Contact, contact_id=contact_id)
    tag = get_object_or_404(Tag, tag_id=tag_id)

    if request.method == 'POST':
        contact.tags.remove(tag)
        messages.success(request, f'Tag "{tag.name}" removed from {contact.name}.')

    return redirect('contacts:contact_detail', contact_id=contact_id)
```

**Step 5: Update tag display template to include remove buttons**

Update `templates/includes/tag_display.html`:

```html
{% if tags %}
<p>
    <strong>Tags:</strong>
    {% for tag in tags %}
        <span style="background-color: #e0e0e0; padding: 2px 8px; margin-right: 4px; border-radius: 3px;">
            {{ tag.name }}
            {% if remove_url_name %}
                <form method="post" action="{% url remove_url_name object_id tag.tag_id %}" style="display: inline;">
                    {% csrf_token %}
                    <button type="submit" style="background: none; border: none; cursor: pointer; padding: 0 4px;">&times;</button>
                </form>
            {% endif %}
        </span>
    {% endfor %}
</p>
{% endif %}
```

**Step 6: Update contact_detail.html to pass remove URL**

Update the include in `templates/contacts/contact_detail.html`:

```html
{% include 'includes/tag_display.html' with tags=contact.tags.all remove_url_name='contacts:remove_tag' object_id=contact.contact_id %}
```

**Step 7: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_views.RemoveTagFromContactTest -v 2`
Expected: PASS (2 tests)

**Step 8: Commit**

```bash
git add apps/contacts/views.py apps/contacts/urls.py templates/includes/tag_display.html templates/contacts/contact_detail.html tests/test_tag_views.py
git commit -m "feat: add remove tag functionality for contacts"
```

---

## Task 12: Add Tag Views for Business

**Files:**
- Modify: `apps/contacts/views.py`
- Modify: `apps/contacts/urls.py`
- Modify: `templates/contacts/business_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing tests**

Add to `tests/test_tag_views.py`:

```python
class AddTagToBusinessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Default",
            last_name="Contact",
            email="default@example.com",
            mobile_number="555-0000"
        )
        self.business = Business.objects.create(
            business_name="Acme Corp",
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()

    def test_add_tag_to_business(self):
        response = self.client.post(
            reverse('contacts:add_business_tag', args=[self.business.business_id]),
            {'tag_name': 'slow payer'}
        )
        self.assertEqual(response.status_code, 302)
        self.business.refresh_from_db()
        self.assertEqual(self.business.tags.first().name, 'slow payer')


class RemoveTagFromBusinessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Default",
            last_name="Contact",
            email="default@example.com",
            mobile_number="555-0000"
        )
        self.business = Business.objects.create(
            business_name="Acme Corp",
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()
        self.tag = Tag.objects.create(name="to remove")
        self.business.tags.add(self.tag)

    def test_remove_tag_from_business(self):
        response = self.client.post(
            reverse('contacts:remove_business_tag', args=[self.business.business_id, self.tag.tag_id])
        )
        self.assertEqual(response.status_code, 302)
        self.business.refresh_from_db()
        self.assertEqual(self.business.tags.count(), 0)
```

**Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_tag_views.AddTagToBusinessTest tests.test_tag_views.RemoveTagFromBusinessTest -v 2`
Expected: FAIL with NoReverseMatch

**Step 3: Add URL patterns**

Add to `apps/contacts/urls.py`:

```python
    path('businesses/<int:business_id>/add-tag/', views.add_tag_to_business, name='add_business_tag'),
    path('businesses/<int:business_id>/remove-tag/<int:tag_id>/', views.remove_tag_from_business, name='remove_business_tag'),
```

**Step 4: Add view functions**

Add to `apps/contacts/views.py`:

```python
def add_tag_to_business(request, business_id):
    business = get_object_or_404(Business, business_id=business_id)

    if request.method == 'POST':
        tag_name = request.POST.get('tag_name', '').strip().lower()
        if tag_name:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            business.tags.add(tag)
            messages.success(request, f'Tag "{tag.name}" added to {business.business_name}.')
        else:
            messages.error(request, 'Tag name is required.')

    return redirect('contacts:business_detail', business_id=business_id)


def remove_tag_from_business(request, business_id, tag_id):
    business = get_object_or_404(Business, business_id=business_id)
    tag = get_object_or_404(Tag, tag_id=tag_id)

    if request.method == 'POST':
        business.tags.remove(tag)
        messages.success(request, f'Tag "{tag.name}" removed from {business.business_name}.')

    return redirect('contacts:business_detail', business_id=business_id)
```

**Step 5: Update business_detail view to pass all_tags**

```python
def business_detail(request, business_id):
    business = get_object_or_404(
        Business.objects.prefetch_related('tags'),
        business_id=business_id
    )
    contacts = Contact.objects.filter(business=business).order_by('last_name', 'first_name')
    all_tags = Tag.objects.all()
    return render(request, 'contacts/business_detail.html', {
        'business': business,
        'contacts': contacts,
        'all_tags': all_tags
    })
```

**Step 6: Update business_detail.html template**

Add tag display and form (after business info, find appropriate location):

```html
{% include 'includes/tag_display.html' with tags=business.tags.all remove_url_name='contacts:remove_business_tag' object_id=business.business_id %}

<h3>Add Tag</h3>
<form method="post" action="{% url 'contacts:add_business_tag' business.business_id %}">
    {% csrf_token %}
    <p>
        <input type="text" name="tag_name" list="existing-tags" placeholder="Enter tag name">
        <datalist id="existing-tags">
            {% for tag in all_tags %}
                <option value="{{ tag.name }}">
            {% endfor %}
        </datalist>
        <button type="submit">Add Tag</button>
    </p>
</form>
```

**Step 7: Run tests to verify they pass**

Run: `python manage.py test tests.test_tag_views.AddTagToBusinessTest tests.test_tag_views.RemoveTagFromBusinessTest -v 2`
Expected: PASS (2 tests)

**Step 8: Commit**

```bash
git add apps/contacts/views.py apps/contacts/urls.py templates/contacts/business_detail.html tests/test_tag_views.py
git commit -m "feat: add tag management functionality for businesses"
```

---

## Task 13: Add Tag Views for Job

**Files:**
- Modify: `apps/jobs/views.py`
- Modify: `apps/jobs/urls.py`
- Modify: `templates/jobs/job_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing tests**

Add to `tests/test_tag_views.py`:

```python
class AddTagToJobTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Customer",
            last_name="One",
            email="customer@example.com",
            mobile_number="555-1111"
        )
        self.job = Job.objects.create(
            job_number="JOB-TAG-001",
            contact=self.contact
        )

    def test_add_tag_to_job(self):
        response = self.client.post(
            reverse('jobs:add_tag', args=[self.job.job_id]),
            {'tag_name': 'reference job'}
        )
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.tags.first().name, 'reference job')


class RemoveTagFromJobTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Customer",
            last_name="One",
            email="customer@example.com",
            mobile_number="555-1111"
        )
        self.job = Job.objects.create(
            job_number="JOB-TAG-002",
            contact=self.contact
        )
        self.tag = Tag.objects.create(name="to remove")
        self.job.tags.add(self.tag)

    def test_remove_tag_from_job(self):
        response = self.client.post(
            reverse('jobs:remove_tag', args=[self.job.job_id, self.tag.tag_id])
        )
        self.assertEqual(response.status_code, 302)
        self.job.refresh_from_db()
        self.assertEqual(self.job.tags.count(), 0)
```

**Step 2: Run tests to verify they fail**

Run: `python manage.py test tests.test_tag_views.AddTagToJobTest tests.test_tag_views.RemoveTagFromJobTest -v 2`
Expected: FAIL with NoReverseMatch

**Step 3: Add URL patterns**

Add to `apps/jobs/urls.py`:

```python
    path('<int:job_id>/add-tag/', views.add_tag_to_job, name='add_tag'),
    path('<int:job_id>/remove-tag/<int:tag_id>/', views.remove_tag_from_job, name='remove_tag'),
```

**Step 4: Add view functions**

Add to `apps/jobs/views.py`:

```python
from apps.core.models import Tag

def add_tag_to_job(request, job_id):
    job = get_object_or_404(Job, job_id=job_id)

    if request.method == 'POST':
        tag_name = request.POST.get('tag_name', '').strip().lower()
        if tag_name:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            job.tags.add(tag)
            messages.success(request, f'Tag "{tag.name}" added to job {job.job_number}.')
        else:
            messages.error(request, 'Tag name is required.')

    return redirect('jobs:detail', job_id=job_id)


def remove_tag_from_job(request, job_id, tag_id):
    job = get_object_or_404(Job, job_id=job_id)
    tag = get_object_or_404(Tag, tag_id=tag_id)

    if request.method == 'POST':
        job.tags.remove(tag)
        messages.success(request, f'Tag "{tag.name}" removed from job {job.job_number}.')

    return redirect('jobs:detail', job_id=job_id)
```

**Step 5: Update job detail view to pass all_tags**

Update the job detail view to include all_tags in context and prefetch job tags.

**Step 6: Update job_detail.html template**

Add tag display and form:

```html
{% include 'includes/tag_display.html' with tags=job.tags.all remove_url_name='jobs:remove_tag' object_id=job.job_id %}

<h3>Add Tag</h3>
<form method="post" action="{% url 'jobs:add_tag' job.job_id %}">
    {% csrf_token %}
    <p>
        <input type="text" name="tag_name" list="existing-tags" placeholder="Enter tag name">
        <datalist id="existing-tags">
            {% for tag in all_tags %}
                <option value="{{ tag.name }}">
            {% endfor %}
        </datalist>
        <button type="submit">Add Tag</button>
    </p>
</form>
```

**Step 7: Run tests to verify they pass**

Run: `python manage.py test tests.test_tag_views.AddTagToJobTest tests.test_tag_views.RemoveTagFromJobTest -v 2`
Expected: PASS (2 tests)

**Step 8: Commit**

```bash
git add apps/jobs/views.py apps/jobs/urls.py templates/jobs/job_detail.html tests/test_tag_views.py
git commit -m "feat: add tag management functionality for jobs"
```

---

## Task 14: Display Related Entity Tags (Contact shows Business tags)

**Files:**
- Modify: `templates/contacts/contact_detail.html`
- Test: `tests/test_tag_views.py`

**Step 1: Write the failing test**

Add to `tests/test_tag_views.py`:

```python
class ContactShowsBusinessTagsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            mobile_number="555-1234"
        )
        self.business = Business.objects.create(
            business_name="Acme Corp",
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()
        self.business_tag = Tag.objects.create(name="advance payment required")
        self.business.tags.add(self.business_tag)

    def test_contact_detail_shows_business_tags(self):
        response = self.client.get(
            reverse('contacts:contact_detail', args=[self.contact.contact_id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "advance payment required")
        self.assertContains(response, "Business Tags:")
```

**Step 2: Run test to verify it fails**

Run: `python manage.py test tests.test_tag_views.ContactShowsBusinessTagsTest -v 2`
Expected: FAIL with "Business Tags:" not found

**Step 3: Update contact_detail view to prefetch business tags**

```python
def contact_detail(request, contact_id):
    contact = get_object_or_404(
        Contact.objects.select_related('business').prefetch_related('tags', 'business__tags'),
        contact_id=contact_id
    )
    all_tags = Tag.objects.all()
    return render(request, 'contacts/contact_detail.html', {
        'contact': contact,
        'all_tags': all_tags
    })
```

**Step 4: Update template to show business tags**

Add to `templates/contacts/contact_detail.html` after the contact tags section:

```html
{% if contact.business and contact.business.tags.exists %}
<p>
    <strong>Business Tags ({{ contact.business.business_name }}):</strong>
    {% for tag in contact.business.tags.all %}
        <span style="background-color: #ffe0b2; padding: 2px 8px; margin-right: 4px; border-radius: 3px;">{{ tag.name }}</span>
    {% endfor %}
</p>
{% endif %}
```

**Step 5: Run test to verify it passes**

Run: `python manage.py test tests.test_tag_views.ContactShowsBusinessTagsTest -v 2`
Expected: PASS

**Step 6: Commit**

```bash
git add apps/contacts/views.py templates/contacts/contact_detail.html tests/test_tag_views.py
git commit -m "feat: display business tags on contact detail page"
```

---

## Task 15: Display Tags on Estimate/Job Views

**Files:**
- Modify relevant estimate detail views and templates
- Test: `tests/test_tag_views.py`

**Step 1: Identify estimate detail view and template**

Check `apps/jobs/views.py` for estimate_detail function and corresponding template.

**Step 2: Write the failing test**

Add to `tests/test_tag_views.py`:

```python
class EstimateShowsRelatedTagsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.contact = Contact.objects.create(
            first_name="Customer",
            last_name="One",
            email="customer@example.com",
            mobile_number="555-1111"
        )
        self.business = Business.objects.create(
            business_name="Customer Corp",
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()
        self.job = Job.objects.create(
            job_number="JOB-EST-001",
            contact=self.contact
        )
        self.job_tag = Tag.objects.create(name="priority")
        self.contact_tag = Tag.objects.create(name="vip")
        self.business_tag = Tag.objects.create(name="advance payment")
        self.job.tags.add(self.job_tag)
        self.contact.tags.add(self.contact_tag)
        self.business.tags.add(self.business_tag)
        # Create estimate - adjust based on actual model structure
        # This step needs to be adapted based on actual Estimate model

    def test_estimate_detail_shows_related_tags(self):
        # Test implementation depends on estimate URL structure
        pass  # Implement after checking estimate views
```

**Step 3: Update estimate views with prefetch_related**

Update estimate detail views to prefetch:
- `job__tags`
- `job__contact__tags`
- `job__contact__business__tags`

**Step 4: Update estimate templates**

Add tag displays showing job, contact, and business tags in relevant estimate templates.

**Step 5: Run all tag tests**

Run: `python manage.py test tests.test_tag_views -v 2`
Expected: All PASS

**Step 6: Commit**

```bash
git add apps/jobs/views.py templates/jobs/
git commit -m "feat: display related entity tags on estimate views"
```

---

## Task 16: Run Full Test Suite and Final Commit

**Step 1: Run all tests**

Run: `python manage.py test -v 2`
Expected: All tests PASS

**Step 2: Create final summary commit**

```bash
git add -A
git commit -m "feat: complete tags feature implementation

- Tag model with normalized names (lowercase, trimmed)
- M2M relationships for Job, Contact, Business
- Tag display on all detail pages
- Add/remove tag functionality with autocomplete
- Business tags shown on contact detail
- Prefetch optimization for all tag queries"
```

---

## Summary

This plan implements:

1. **Tag Model** (Task 1, 5): Normalized tag storage with unique, lowercase names
2. **M2M Relationships** (Tasks 2-4): Tags linkable to Contact, Business, Job
3. **Display** (Tasks 6-9, 14-15): Tags visible on all detail pages with related entity tags
4. **Management** (Tasks 10-13): Add/remove tags with HTML5 datalist autocomplete
5. **Performance** (throughout): prefetch_related to minimize database queries

Total: ~16 tasks, each with TDD approach (test first, then implement)
