# ThinkPHP 6 Route Resolution

Use this reference when mapping an Apifox `method + endpoint` to ThinkPHP 6 code.

## Required Exploration Gate

Before reading route files, listing project files, running route discovery commands, or validating inferred controller/action classes in the target repository, use `my-explore-0` and follow its constraints.

## Route Sources

Check project conventions first. Common ThinkPHP 6 sources:

- `route/*.php`
- route files loaded by service providers or config
- annotations/attributes only if the project already uses them
- framework route cache or `php think route:list` when available

Do not assume the endpoint maps directly to controller/action until route evidence is found.

## Explicit Route Patterns

Resolve these forms:

```php
Route::get('user/:id', 'User/read');
Route::post('orders', 'api.Order/create');
Route::any('sync', 'Sync/index');
Route::group('admin', function () {
    Route::post('users', 'admin.User/save');
});
Route::resource('orders', 'Order');
```

Account for:

- HTTP method matching.
- group prefixes and nested groups.
- module/controller/action notation.
- namespace or route binding conventions.
- route variables such as `:id`, `<id>`, or typed patterns.
- chain calls such as `->middleware()`, `->domain()`, `->pattern()`, `->completeMatch()`.
- route aliases and miss routes.

## Default Route Fallback

Only use default routing after explicit routes fail. For TP6, default routing usually derives module/controller/action from path segments according to project config. Validate the inferred class and method exists before treating it as resolved.

## Resolution Output

Return:

```text
Routing
- matched method/endpoint:
- route definition:
- controller:
- action:
- middleware/auth:
- route params:
- confidence: high|medium|low
- evidence:
```

If confidence is low and implementation would create or change behavior, stop and ask the user.
