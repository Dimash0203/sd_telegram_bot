# ServiceDesk API — Create Ticket (`POST /api/v1/ticket`)

This document explains the **Create Ticket** API call, the **required dependencies** (entities that must already exist in the database),
and the **common validation / database errors** you may see while testing in Postman.

---

## Endpoint

- **Method:** `POST`
- **Path:** `/api/v1/ticket`
- **Content-Type:** `application/json`

Creates a new **Ticket** record in the Service Desk system.

---

## High-level behavior

When you call `POST /api/v1/ticket`, the backend:

1. Deserializes your JSON into a request DTO (e.g., `TicketCreateRequest`)
2. Runs **Bean Validation** (e.g., `@NotBlank`, `@Range(min=1)`)
3. Maps the request to a JPA/Hibernate `Ticket` entity
4. Inserts a row into the `ticket` table
5. Enforces **foreign key (FK)** constraints for referenced entities (author/category/service/address/etc.)

---

## Entity dependencies (what must already exist)

A Ticket references other entities. If you reference an entity by `id`, it **must exist** in the corresponding table.

### 1) `author` (User)
- Ticket column: `author_id` → FK to `users.id`
- Meaning: the requester who created the ticket

**Rule:** If you send `author.id`, that user must exist, otherwise you get an FK error:
`Key (author_id)=(...) is not present in table "users"`.

✅ Your real example user:
```json
{
  "id": 3,
  "username": "polzovatel@logitex.kz",
  "role": "USER",
  "address": { "id": 1, "region": "ASTANA", "fullAddress": "..." }
}
```

> Note: Many systems derive author from the auth token, but your backend clearly inserts `author_id`,
so you must provide a valid author (or the backend must set it server-side).

---

### 2) `category`
- Ticket column: `category_id` → FK to `category.id`
- Meaning: classification group for the ticket

**Rules you already observed:**
- `category.name` is **NotBlank** (must not be null/empty)
- `category.id` must exist (FK)

✅ Your real example category:
```json
{
  "id": 1,
  "name": "test",
  "type": "VS"
}
```

---

### 3) `service`
- Ticket column: `service_id` → FK to `service.id`
- Meaning: specific service item (usually belongs to a category)

**Rules you already observed:**
- `service.name` is **NotBlank**
- `service.executionTimestamp` must be in range **[1..Long.MAX]** (so `0` is invalid)
- `service` must reference a **persisted** Service entity (existing row)
  - If you send only `{ "name": "...", ... }` without a real `id`, you can get Hibernate:
    `TransientPropertyValueException: ... Ticket.service -> Service`

✅ Your real example service:
```json
{
  "id": 1,
  "name": "test",
  "executionTimestamp": 10,
  "category": { "id": 1, "name": "test", "type": "VS" }
}
```

---

### 4) `address`
- Ticket column: `address_id` → FK to `address.id`
- Meaning: location of the request/issue

**Rule:** `address.id` must exist, otherwise FK fails.

✅ Your real address (from the user):
```json
{
  "id": 1,
  "region": "ASTANA",
  "location": "Шевченко",
  "building": "Офис",
  "cabinet": "1",
  "fullAddress": "г. Астана, Шевченко, Офис, 1"
}
```

---

### 5) `executor` (optional on create)
- Ticket column: `executor_id` → typically FK to `users.id`
- Meaning: assigned agent/performer

You can set:
- `executor: null` → unassigned
- or `executor: { "id": <existingUserId> }`

---

### 6) `solution` (usually optional on create)
- Ticket column: `solution_id` → FK to `solution.id`
- Meaning: resolution method (often set on closing)

Typically `null` at create time.

---

### 7) `files` (often optional / separate upload flow)
- Many systems upload files via a separate endpoint and then attach them by id/url.
- Safe default for create: `files: []`

---

## Full working request body (using your REAL user/category/service/address)

```json
{
  "title": "Тестовый тикет из Postman",
  "description": "Создание тикета от пользователя polzovatel@logitex.kz",
  "sla": "LOW",
  "author": {
    "id": 3,
    "username": "polzovatel@logitex.kz",
    "firstname": "Polzovatel",
    "lastname": "Polzovatel",
    "phone": null,
    "role": "USER",
    "address": {
      "id": 1,
      "region": "ASTANA",
      "location": "Шевченко",
      "building": "Офис",
      "cabinet": "1",
      "fullAddress": "г. Астана, Шевченко, Офис, 1"
    },
    "active": true,
    "job": null,
    "workphone": "1",
    "chatId": null,
    "type": "VS",
    "fio": "Polzovatel Polzovatel"
  },
  "executor": null,
  "category": {
    "id": 1,
    "name": "test",
    "type": "VS"
  },
  "service": {
    "id": 1,
    "name": "test",
    "executionTimestamp": 10,
    "category": {
      "id": 1,
      "name": "test",
      "type": "VS"
    }
  },
  "files": [],
  "address": {
    "id": 1,
    "region": "ASTANA",
    "location": "Шевченко",
    "building": "Офис",
    "cabinet": "1",
    "fullAddress": "г. Астана, Шевченко, Офис, 1"
  },
  "kind": "TICKET",
  "solution": null,
  "createdTimestamp": 1736341800000
}
```

> `createdTimestamp` can be any positive number. Often it is epoch milliseconds.
> If your backend sets timestamps itself, it may ignore this value.

---

## Postman testing checklist

1. **Authenticate** (use the correct method your backend expects: Bearer token or session cookie)
2. Add headers:
   - `Content-Type: application/json`
   - `Accept: application/json`
   - `Authorization: Bearer <token>` (if JWT)
3. Verify dependencies exist:
   - `GET /api/v1/category` contains `id=1`
   - `GET /api/v1/service` contains `id=1`
   - `GET /api/v1/users` (or equivalent) contains `author.id=3`
4. Run `POST /api/v1/ticket` with the body above.

---

## Common errors and what they mean

### `Request method 'GET' is not supported` (on authenticate URL)
You opened the auth URL in a browser (GET). Authentication endpoint expects **POST**.

### `403 Forbidden`
Authorization/permission issue:
- missing token/cookie
- wrong role/permission for creating tickets
- CSRF required (if cookie-based sessions)

### Validation: `service.executionTimestamp` rejected value `0`
Your backend requires a positive value:
- must be **between 1 and 9223372036854775807**

### Validation: `category.name` / `service.name` required
Backend has `@NotBlank` on those fields. They cannot be null/empty.

### FK constraint failures (`Key (...) is not present in table ...`)
You referenced an id that does not exist in the DB for that table.

### Hibernate: `TransientPropertyValueException ... Ticket.service -> Service`
You referenced a **non-persisted** Service object (no real `service.id`).
Solution: reference an existing service row by id (as in the working body above).

---

## Notes

- Swagger “Example Value” often shows a **full object**; it does **not** mean every field is required.
- Your backend’s validation errors are the authoritative guide for what is required.
- Prefer using real ids from `GET` lists to avoid FK errors.
