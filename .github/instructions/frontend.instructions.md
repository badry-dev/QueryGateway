# Frontend Instructions (Vite + React SPA)

## Do
- Build only admin console features in `frontend/`.
- Use React + TypeScript + Tailwind + shadcn/ui.
- Keep API clients aligned to `/api/v1/admin/*` and `/api/v1/data/*`.
- Implement wizard UX for Module 2 with a rich SQL editor.
- Use the existing CodeMirror 6 integration (`@uiw/react-codemirror`) for SQL authoring.
- Provide explicit validation errors for bind params and auth setup.
- Keep preview samples separate from persisted endpoint defaults and schedule bindings.
- For snapshot endpoints, require a cached output column and `eq`/`gte`/`lte` operator for every
  request parameter in create and edit flows.
- Write component tests for wizard steps and critical forms.

## Do Not
- Do not implement backend business logic in frontend.
- Do not hardcode secrets, tokens, or private endpoints.
- Do not call unversioned API paths.
- Do not bypass typed client models.

## Frontend Validation Commands
- `cd frontend && npm install`
- `cd frontend && npm run dev`
- `cd frontend && npm run eslint`
- `cd frontend && npm run prettier:check`
- `cd frontend && npm run test`

## UI Contract Rules
- Wizard must enforce bind variable awareness (`:param_name`).
- Endpoint creation UI must expose auth assignment and data strategy selection.
- Show clear status for live-query vs scheduled-snapshot behavior.
- Explain that schedule bindings control what Oracle loads, while snapshot filter mappings control
  which cached rows an authenticated data request returns; neither replaces authentication.
- Surface backend validation errors verbatim when safe.

## Stop Conditions
- API payload uncertainty: check backend OpenAPI/spec and existing API client types.
- Ambiguous workflow state: inspect existing wizard store/components before adding new state model.
