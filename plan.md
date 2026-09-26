# Classroom Web App Plan

## Current Status

The first working vertical slice is implemented and running locally.

Completed:

- [x] Django project foundation, settings, migrations, admin, and health endpoints.
- [x] Django REST Framework API with authentication and ownership checks.
- [x] GitHub OAuth login, callback, logout, and encrypted token storage.
- [x] Standalone GitHub REST client with pagination, timeouts, and safe errors.
- [x] Course and assignment data models.
- [x] Draft-only assignment import/create workflow.
- [x] GitHub organization discovery and selection-time template discovery.
- [x] Explicit assignment publishing that links existing repositories and creates missing ones.
- [x] Repository retry for students who did not accept invitations or whose setup failed.
- [x] GitHub Actions report collection, score parsing, late penalties, and Eastern time display.
- [x] Color-coded scores and submission dates.
- [x] Report filters and sorting.
- [x] Bounded concurrent GitHub requests with per-repository failure isolation.
- [x] Celery report jobs with progress tracking and a local eager mode that does not require Redis.
- [x] Browser dashboard, import page, report page, and report refresh action.
- [x] Deployment guidance in [DEPLOYMENT.md](DEPLOYMENT.md).

Current local mode:

```text
CELERY_TASK_ALWAYS_EAGER=true
```

This avoids Docker, Redis, and a separate Celery worker during development. Production should use the queued worker architecture described below.

Remaining:

- [ ] Test repository retry against a real missing invitation.
- [ ] Test report refresh after a new late submission.
- [ ] Create a Git checkpoint commit for the completed foundation.
- [ ] Add PostgreSQL configuration using `DATABASE_URL`.
- [ ] Add production deployment configuration and process supervision.
- [ ] Add stronger GitHub rate-limit and retry handling.
- [ ] Decide whether a GitHub App should replace the OAuth token model.
- [ ] Add frontend editing for existing drafts.
- [ ] Evaluate FastAPI only if a concrete service boundary appears.

## 1. Product Goal

Build a web application that helps instructors manage GitHub Classroom-style assignments:

- Connect an instructor account to a GitHub organization.
- Create student repositories from template repositories.
- Add students as repository collaborators.
- Monitor GitHub Actions workflow results.
- Extract scores from workflow logs.
- Apply due dates and late penalties.
- Display assignment reports in a web interface.

The existing `create_assignment.py` and `report_assignment.py` scripts provide behavior to preserve, but their implementation does not need to be copied directly into the web application.

## 2. Initial Architecture

Start with one Django application rather than multiple backend services:

```text
Browser
  -> Django + Django REST Framework
       -> Application services
            -> GitHub API client
                 -> GitHub REST API
       -> PostgreSQL
```

Initial technologies:

- Django for the application, authentication, ORM, and admin.
- Django REST Framework for JSON API endpoints.
- PostgreSQL for the production database.
- SQLite for simple local development, if convenient.
- `requests` or an equivalent HTTP client for GitHub API calls.
- Celery and Redis after long-running workflows need background processing.

FastAPI is deferred until there is a concrete need for a separate service, such as high-volume asynchronous processing or an independently deployed webhook service.

## 3. First Vertical Slice

The first complete milestone should support this workflow:

1. An instructor signs in.
2. The instructor creates an assignment from a template repository.
3. The application validates the GitHub organization and template repository.
4. The application creates repositories for selected students.
5. The application records each repository and any individual failures.
6. The instructor requests a report.
7. The application retrieves the latest workflow results and returns structured scores.

This slice should work through the API before building a polished frontend.

## 4. Proposed Project Structure

```text
classroom/
    manage.py
    config/
        settings/
        urls.py
        asgi.py
        wsgi.py
    accounts/
    assignments/
    github_integration/
    reports/
    api/
```

Responsibilities:

- `accounts`: users, roles, authentication, and GitHub connections.
- `assignments`: courses, assignments, students, and student repositories.
- `github_integration`: GitHub API client and GitHub-specific operations.
- `reports`: workflow result collection, score extraction, and report calculation.
- `api`: serializers, viewsets, routes, and API permissions.

## 5. Implementation Phases

### Phase 0: Capture Current Behavior - Completed

- Identify the inputs, outputs, and error cases of both existing scripts.
- Preserve the current score formats and late-penalty rules.
- Decide which GitHub operations are required for the first release.
- Add or retain tests for score parsing and date calculations before moving logic.

### Phase 1: Create the Django Foundation - Completed

- Create the Django project and initial applications.
- Configure development and production settings.
- Add environment-based configuration.
- Configure Django authentication and the admin site.
- Add a health-check endpoint.
- Add formatting, linting, and test commands.

### Phase 2: Design and Add the Data Model - Completed for Initial Slice

Initial models:

- `User`
- `GitHubConnection`
- `Course`
- `Assignment`
- `Student`
- `StudentRepository`
- `WorkflowRun`
- `WorkflowJob`
- `Score`
- `Report`

An assignment should include:

- Name and description.
- GitHub organization.
- Template repository.
- Due date with timezone.
- Late penalty.
- Creator and course.
- Status and timestamps.

Use database constraints for uniqueness, especially for student repositories and assignments within a course.

### Phase 3: Build the GitHub Integration Layer - Completed for Initial Slice

Create a service boundary around GitHub instead of calling GitHub from views.

Required operations:

- Verify organization access.
- Retrieve organization members.
- Retrieve and validate a template repository.
- Create a repository from a template.
- Add a repository collaborator.
- Retrieve workflow runs.
- Retrieve workflow jobs.
- Download job logs.

The client should provide consistent exceptions, timeouts, pagination, rate-limit handling, and safe debug logging. Authorization headers and token values must never be logged.

### Phase 4: Add GitHub Authentication and Secret Storage - Completed for Local OAuth

Begin with a development-only token flow so the application can be tested. Move toward GitHub OAuth or a GitHub App for real deployments.

Security requirements:

- Store only the minimum token or credential data required.
- Encrypt GitHub tokens before storing them in the database.
- Keep the encryption key outside the database, supplied through environment configuration locally.
- Use a secrets manager or KMS for production deployments.
- Never expose tokens through serializers, logs, error messages, or admin list views.
- Track token scopes, expiration, last-used time, and revocation status.
- Support credential replacement and revocation.

Database encryption protects stored values, but it does not protect the application if both the database and encryption key are compromised.

### Phase 5: Implement Assignment Import, Publishing, and Retry - Completed

The application now has separate draft, publish, and retry operations:

```text
create_assignment_repositories(assignment, students)
```

The service should:

1. Validate the template repository.
2. Validate repository names and student identities.
3. Create repositories for each student.
4. Save successful repository records.
5. Add collaborators with the intended permission.
6. Record per-student failures.
7. Return a summary suitable for the API and frontend.

One failed repository should not silently prevent the remaining students from being processed.

### Phase 6: Implement Report Services - Completed

Create reusable report services independent of HTTP and presentation:

```text
collect_assignment_results(assignment)
calculate_scores(results)
calculate_late_penalties(results)
build_report(assignment)
```

Preserve the existing behavior:

- Select the latest workflow run.
- Retrieve jobs for that run.
- Download and decode job logs.
- Extract supported score formats.
- Compare the workflow time with the timezone-aware due date.
- Apply late penalties.
- Return structured report data.

The API should return JSON. A CLI or future frontend can decide how that data is displayed.

### Phase 7: Add the REST API - Initial Slice Completed

Initial endpoints:

```text
POST   /api/assignments/
GET    /api/assignments/
GET    /api/assignments/{id}/
PATCH  /api/assignments/{id}/
DELETE /api/assignments/{id}/

POST   /api/assignments/{id}/publish/
GET    /api/assignments/{id}/repositories/
GET    /api/assignments/{id}/report/
POST   /api/assignments/{id}/refresh-results/
POST   /api/assignments/{id}/report-jobs/
GET    /api/report-jobs/{id}/

GET    /api/github/organizations/
GET    /api/github/templates/
```

Use serializers for input validation and permissions for access control. Return consistent error responses and do not expose internal GitHub exceptions directly.

### Phase 8: Handle Long-Running Work - Local and Initial Production Foundation Completed

Report generation now has a durable background-job foundation. The API queues work and exposes job status/progress while Celery workers perform bounded concurrent GitHub collection.

Target design:

```text
Django API -> Celery task -> Redis -> GitHub API
```

The API should return a task identifier and status for queued work. Store task progress and failures so the frontend can display useful results.

Local worker command:

```text
celery -A config worker --loglevel=INFO -P solo
```

Redis must be running at the configured broker URL before queueing jobs.

### Phase 9: Build the Initial Frontend - Initial Slice Completed

Initial screens:

- Login.
- Course dashboard.
- Assignment list.
- Create-assignment form.
- Repository-provisioning progress.
- Assignment report.
- GitHub connection settings.

Use Django admin as the first internal management interface while the API and workflows are being developed.

### Phase 10: Evaluate FastAPI - Deferred

Only introduce FastAPI after identifying a concrete boundary. Possible candidates include:

- GitHub webhook ingestion.
- An independently deployed asynchronous worker service.
- A service with separate scaling or runtime requirements.

Until then, Django REST Framework should remain the single API layer.

## 6. Testing Strategy

Add tests at the service boundaries:

- Score extraction for every supported score format.
- Timezone-aware due-date parsing.
- Late-penalty calculations.
- GitHub client requests using mocked HTTP responses.
- Pagination and GitHub API error handling.
- Assignment repository provisioning.
- Per-student failure handling.
- API authentication and permissions.
- Token encryption and serializer redaction.
- Report generation from representative workflow data.

The GitHub client, assignment services, and report services should be testable without starting a web server or contacting GitHub.

## 7. Initial Definition of Done

The base app is ready for the next stage when:

- An instructor can authenticate.
- An assignment can be created through the API.
- A configured GitHub connection can validate an organization and template.
- Student repositories can be provisioned and recorded.
- Individual GitHub failures are visible and recoverable.
- A report can be generated from workflow runs and logs.
- GitHub credentials are encrypted and never returned by the API.
- Core workflows have automated tests.
- The CLI behavior has either been preserved or intentionally replaced by documented application services.

The initial definition of done is now met for local development. The remaining work is production hardening and real-world workflow verification.

## 8. Recommended Build Order

```text
Django project
  -> authentication
  -> models and migrations
  -> GitHub client
  -> encrypted GitHub connections
  -> assignment provisioning service
  -> report service
  -> REST endpoints
  -> background tasks
  -> frontend
  -> FastAPI evaluation
```

## 9. Next Steps

1. Verify repository retry with one student who has not accepted an invitation.
2. Verify report refresh after a new GitHub Actions run appears.
3. Create a Git checkpoint commit before the next feature slice.
4. Add PostgreSQL settings and a production `DATABASE_URL` path.
5. Choose a deployment platform and configure web, worker, Redis, database, and HTTPS.
6. Run `python manage.py check --deploy` and complete a staging deployment.
7. Decide whether to keep OAuth tokens or migrate to a GitHub App.
