# Judge audit: claude-sonnet-5-5_effort-high (12 of 46 judgments, seed 20261103)

For each item, decide yourself whether any finding matches the known bug, then compare with the judge.

## angular/bug-50063 condition B

**Known bug:** While replacing `global` with `globalThis`, the PR removed the guards around the Jasmine/Jest hooks in `@angular/core/testing` test_hooks.ts: `if (_global.beforeEach) {...}` became an unconditional `beforeEach(...)` / `afterEach(...)`. When this module is evaluated outside a test runner (e.g. it ends up in an application bundle), `beforeEach` is undefined and loading the module throws a ReferenceError. Fixed by calling `globalThis.beforeEach?.(...)` / `globalThis.afterEach?.(...)`.

**Findings:**

0. `packages/core/testing/src/test_hooks.ts:19` (medium, conf 0.6): The old code guarded with `if (_global.beforeEach)` and `if (_global.afterEach)`. The new code calls `beforeEach(...)` and `afterEach(...)` unconditionally at module load. If `@angular/core/testing` is imported where no test framework globals exist, for example when the file ends up in a server bundle or a non-Jasmine/Mocha/Jest runner, evaluating the module throws `ReferenceError: beforeEach is not defined`. This is a regression from the previously safe behavior.

**Judge:** matched [0]: Finding 0 pinpoints the removed `if (_global.beforeEach)`/`afterEach` guards in test_hooks.ts, noting that the hooks are now called unconditionally at module load. It also identifies that evaluating the module outside a test framework throws `ReferenceError: beforeEach is not defined`. This is exactly the known bug.

**Your verdict:** ☑ agree ☐ disagree (note: ...)

## angular/bug-53695 condition C

**Known bug:** The PR adds support for default imports in `@defer` dependencies and records `isDefaultImport` in the `deferrableTypes` map, but never sets `deferBlockDep.isDefaultImport` on the per-block dependency objects (they keep the initial `isDefaultImport: false`). The generated dependency loader function for the defer block reads that flag, so for a default-imported component it emits `m.ComponentName` instead of `m.default`, and loading the deferred block yields undefined. Fixed by setting `deferBlockDep.isDefaultImport = isDefaultImport(importDecl)` in `collectDeferredSymbols`.

**Findings:**

0. `packages/compiler-cli/src/ngtsc/annotations/component/src/handler.ts:1621` (low, conf 0.25): isDefaultImport() returns false whenever the import has named bindings. For a combined import such as `import CmpA, {Other} from './cmp-a'`, where CmpA is the default import and is used in a @defer block or deferredImports, the generated loader becomes `m => m.CmpA` instead of `m => m.default`. At runtime that resolves to undefined and the deferred dependency fails to load.

**Judge:** matched none: The known bug is that `collectDeferredSymbols` never sets `deferBlockDep.isDefaultImport` on the per-block dependency objects, so they stay `false`. As a result, the per-block loader emits `m.Name` even for a plain default import. Finding [0] describes a different mechanism: `isDefaultImport()` misclassifying combined imports like `import CmpA, {Other}` because of how it checks named bindings. It does not identify the missing assignment on `deferBlockDep`, so it does not match.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## angular/bug-55796 condition A

**Known bug:** To avoid mutating readonly/frozen listener options, the PR copies them with `{...options}` in `copyEventListenerOptions` before passing them to the native `addEventListener` (special-casing only `signal`). Object spread copies only own enumerable data properties, while the native call reads each option via [[Get]]. Options supplied as getters, on the prototype, or as non-enumerable properties are silently dropped: `capture: true` becomes bubbling, `once: true` fires repeatedly, and the MDN `passive` feature-detection getter is never invoked. Fixed by also reading `capture`, `once`, `passive` and `signal` from the source object when the spread did not copy them.

**Findings:**

0. `packages/zone.js/lib/common/events.ts:603` (low, conf 0.12): The post-schedule restore of `once` now uses `taskData.options.once = true`. `taskData` is a shared global object, so `taskData.options` can be overwritten if `scheduleEventTask` or a zone hook (such as `onScheduleTask`) triggers a nested `addEventListener`. In that case the `once` flag would be set on the wrong options object, or the local `options` would never get `once` restored. The previous code used the local `options` reference, which is safe against this.

**Judge:** matched none: The known bug is that `copyEventListenerOptions` uses object spread, which drops getter, prototype and non-enumerable option properties (`capture`, `once`, `passive`). Finding [0] instead raises re-entrancy on the shared `taskData` affecting the `once` restore ("`taskData.options` can be overwritten... nested `addEventListener`"). That is a different mechanism, and it does not concern the spread losing properties.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## django/bug-f920937c8a condition A

**Known bug:** To skip the regex for converter-less routes, `RoutePattern.match()` now compares the path with `self._route` using string operations (`==`, `startswith`, `removeprefix`). `_route` can be a lazy translation object (`gettext_lazy()` routes, e.g. with i18n URL patterns). Lazy proxies don't behave like `str` for `str.startswith()` / `str.removeprefix()`, so such routes fail to match or raise. Fixed by coercing the route with `str(self._route)` at match time.

**Findings:**

0. `django/urls/resolvers.py:342` (high, conf 0.55): In the new non-endpoint, no-converter branch, `path.startswith(self._route)` and `path.removeprefix(self._route)` use `self._route` directly. For translated routes (`path(_('translated/'), include(...))`) it is a lazy string proxy, not a `str`. `str.startswith` raises `TypeError` for it, so resolving any include-style prefix with a lazily translated route crashes. The old regex path handled this through `LocaleRegexDescriptor`, which evaluates the translation for the active language. The new code should use `str(self._route)`. Matching also ignores the active language, because `converters` is computed once.

**Judge:** matched [0]: Finding 0 identifies the same defect. It says `path.startswith(self._route)` / `removeprefix` are given a lazy translation proxy, which causes a TypeError or failure to match. It also proposes the same fix, `str(self._route)`, which is the known bug and its fix.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## angular/bug-60875 condition B

**Known bug:** RouterLink on anchor elements now only subscribes to router NavigationEnd events (to recompute `href`) when `subscribeToNavigationEventsIfNecessary` decides the link depends on router state, i.e. only for `preserveFragment` or `queryParamsHandling` 'merge'/'preserve' (plus a muddled clause about the default handling). But the href of a relative link also changes whenever navigation changes the ActivatedRoute it resolves against. E.g. `<a [routerLink]="['./child']" queryParamsHandling="replace">` keeps showing `/initial/child` after navigating to `/different`. The optimization's premise is wrong, so hrefs go stale after navigation. The fix removes the condition and always subscribes for anchor elements (effectively rolling back the PR).

**Findings:**

0. `packages/router/src/directives/router_link.ts:258` (high, conf 0.85): The condition in the constructor is inverted. `if (!this.isAnchorElement) { this.subscribeToNavigationEventsIfNecessary(); } else { this.setTabIndexIfNotOnNativeEl('0'); }`. For non-anchor hosts the helper returns immediately, so the call does nothing. For anchor hosts (`<a>`, `<area>`, compatible custom elements) the else branch runs and sets `tabindex="0"` on a natively focusable element, which is a behavior regression. Anchors also skip the NavigationEnd subscription in the constructor, so href is only subscribed after the first ngOnChanges. Non-anchor elements still get the tabindex. The condition should be `if (this.isAnchorElement)`.

**Judge:** matched none: Finding 0 is about the inverted `if (!this.isAnchorElement)` check in the constructor. It reports that tabindex gets set on anchors and that the subscription is deferred until the first ngOnChanges ("href is only subscribed after the first ngOnChanges"). That assumes anchors still get subscribed eventually. It never identifies the real defect: `subscribeToNavigationEventsIfNecessary` skips the NavigationEnd subscription based on preserveFragment/queryParamsHandling, so relative links with e.g. queryParamsHandling='replace' never update their href when the ActivatedRoute changes. This is a different mechanism.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## django/bug-a9fe98d5bd condition C

**Known bug:** In `urlize`, the simple-URL regex for bare domains is changed to use `DomainNameValidator.hostname_re` before the TLD. `hostname_re` matches a single DNS label (no dots), so bare multi-label domains without `www.` or a scheme, e.g. `docs.djangoproject.com`, no longer match and are not turned into links (`djangoproject.com` still works). Fixed by appending `DomainNameValidator.domain_re`, which matches the additional dotted labels.

**Findings:**

0. `django/utils/html.py:299` (high, conf 0.85): `DomainNameValidator.hostname_re` matches a single DNS label with no dots. The new `simple_url_2_re` is `^(?!http)<one label>\.(com|edu|...)($|/.*)$`, so it only accepts `label.tld`. Words with subdomains and no `www.` or scheme, such as `docs.djangoproject.com`, `mail.google.com` or `foo.example.org/path`, used to be urlized and now are left as plain text. `DomainNameValidator.domain_re` (the repeated `.label` part) needs to be included between the hostname and the TLD.

**Judge:** matched [0]: Finding 0 matches the known bug. It says `hostname_re` "matches a single DNS label with no dots", so multi-label domains such as `docs.djangoproject.com` are no longer urlized. It also proposes the same fix as the ground truth: include `domain_re` between the hostname and the TLD.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## django/bug-bdbda29c3e condition A

**Known bug:** To avoid mutating the original view, `non_atomic_requests()` now wraps the view in a new synchronous `def wrapper(*args, **kwargs): return view(*args, **kwargs)`. For an async view this wrapper is a sync function returning a coroutine, so Django no longer recognizes the decorated view as async (`iscoroutinefunction` is False), and async views decorated with `@transaction.non_atomic_requests` break. Fixed by creating an `async def` wrapper when the view is a coroutine function.

**Findings:**

0. `django/db/transaction.py:346` (high, conf 0.8): The new wrapper is always a plain synchronous function. When `non_atomic_requests` is applied to an `async def` view, the result is no longer a coroutine function, so `iscoroutinefunction` returns False. Django's handler will then treat the view as sync and run it in a thread, and it will get back an un-awaited coroutine instead of an HttpResponse. Async views decorated with `@non_atomic_requests` therefore break with an error like 'didn't return an HttpResponse object. It returned an unawaited coroutine'. This is a regression for existing users, and the wrapper needs an async variant.

**Judge:** matched [0]: Finding 0 identifies the bug exactly. It notes that the new wrapper is "always a plain synchronous function", so for `async def` views "iscoroutinefunction returns False" and the decorated async views break. It also says an async variant of the wrapper is needed, which matches both the known bug and its fix.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## angular/bug-53695 condition B

**Known bug:** The PR adds support for default imports in `@defer` dependencies and records `isDefaultImport` in the `deferrableTypes` map, but never sets `deferBlockDep.isDefaultImport` on the per-block dependency objects (they keep the initial `isDefaultImport: false`). The generated dependency loader function for the defer block reads that flag, so for a default-imported component it emits `m.ComponentName` instead of `m.default`, and loading the deferred block yields undefined. Fixed by setting `deferBlockDep.isDefaultImport = isDefaultImport(importDecl)` in `collectDeferredSymbols`.

**Findings:**

0. `packages/compiler-cli/src/ngtsc/annotations/component/src/handler.ts:1621` (low, conf 0.3): isDefaultImport() returns true only when the import has no namedBindings. For a mixed import such as `import CmpA, {Other} from './cmp-a'`, or `import {default as CmpA} from './cmp-a'`, namedBindings is defined, so a default-bound symbol is reported as non-default. The generated dynamic import then uses `m.CmpA` instead of `m.default`, which resolves to undefined at runtime. Conversely, with `import Default, {Named}`, the check does not look at which binding the symbol actually uses.

**Judge:** matched none: The known bug is that `deferBlockDep.isDefaultImport` is never set in `collectDeferredSymbols`, so per-block deps keep `false` even for simple default imports. Finding [0] criticizes the `isDefaultImport()` heuristic, saying it mishandles mixed imports or `{default as X}`. That is a different defect, and it would not lead a maintainer to the missing assignment on the per-block dependency objects.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## angular/bug-48558 condition C

**Known bug:** To avoid treating the space in an escaped selector (".\fc ber") as a combinator, the PR skips a separator when the preceding part matches `_placeholderRe` (`__ph-N__`) and the next character is a hex digit. But SafeSelector uses the same `__ph-N__` placeholder for attribute selectors and other content, not only for escape sequences. In minified CSS without spaces, e.g. `:host[foo]>div`, the `>` separator is skipped because the part contains an attribute placeholder and the next char 'd' is hex, so the selector is scoped incorrectly and styles on :host attributes break in production builds. Fixed by giving escapes their own `__esc-ph-N__` placeholder and checking only for that.

**Findings:**

0. `packages/compiler/src/shadow_css.ts:739` (high, conf 0.8): The new skip condition is far too broad. It fires whenever the pending `part` contains any `__ph-N__` placeholder and the character after the separator is a hex digit. It does not check that the placeholder is an escape sequence, that the separator is a space, or that the placeholder ends the part. Placeholders are also used for attribute selectors (`[attr]`) and `:nth-*(...)` expressions. So `[type=text] button {}`, `div[foo] a {}`, `.x:nth-child(2n+1) b {}` and `.a\:b .c {}` are all treated as one compound selector. The descendant combinator is swallowed and the preceding part is never scoped. This is a regression: `[type=text] button` now becomes `[type=text] button[contenta]` instead of `[type=text][contenta] button[contenta]`, breaking style encapsulation. The check also ignores the separator type, so `.a\:b>a`, `.a\:b+b` and `.a\:b~c` (with `>`, `+`, `~` as the separator) are skipped as well.

**Judge:** matched [0]: Finding 0 identifies the same faulty condition: it says "it fires whenever the pending `part` contains any `__ph-N__` placeholder and the character after the separator is a hex digit" and notes that "placeholders are also used for attribute selectors (`[attr]`)". It then shows the same consequence, separators being swallowed and the preceding part going unscoped, including for `>` separators. This is the same mechanism as the known bug's `:host[foo]>div` case.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## django/bug-7142667340 condition B

**Known bug:** The commit replaces a custom dict representer with `yaml.dump(..., Dumper=DjangoSafeDumper, sort_keys=False, **self.options)`. If the caller passes `sort_keys` as a serializer option (e.g. `serializers.serialize("yaml", qs, sort_keys=True)`), the keyword is given twice and `yaml.dump()` raises `TypeError: got multiple values for keyword argument 'sort_keys'`. Fixed with `self.options.setdefault("sort_keys", False)`.

**Findings:**

0. `django/core/serializers/pyyaml.py:62` (low, conf 0.35): `sort_keys=False` is now passed explicitly alongside `**self.options`. If a caller passes `sort_keys` as a serializer option, e.g. `serializers.serialize('yaml', qs, sort_keys=True)`, `yaml.dump` receives the keyword twice and raises `TypeError: got multiple values for keyword argument 'sort_keys'`. Before this change the option was accepted, because the dict representer ignored it. The fix is to use `self.options.setdefault('sort_keys', False)` instead of a hard-coded keyword.

**Judge:** matched [0]: Finding [0] describes the same defect as the known bug. It says that passing `sort_keys` as a serializer option makes `yaml.dump` receive the keyword twice and raise "TypeError: got multiple values for keyword argument 'sort_keys'". It also proposes the same fix, `setdefault`.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## angular/bug-67032 condition B

**Known bug:** `cancelLeavingNodes` now force-removes any element tracked as leaving for the same TNode whenever it sits in a different DOM parent than the newly inserted element (added to de-duplicate dynamic components re-rendered into a fresh overlay pane). `leavingNodes` is keyed by TNode, which is shared by every instance of a template, so distinct sibling instances (e.g. an accordion where opening section B collapses section A in another parent) are also "different parent": the still-animating element is removed synchronously and its `animate.leave` animation is skipped. Fixed by tracking the declaration view of each leaving element and only doing the cross-parent removal for the same logical view.

**Findings:**

0. `packages/core/src/animation/utils.ts:163` (medium, conf 0.5): `leavingNodes` is keyed by `tNode`, which is shared by every instance of a template or component, and `cancelLeavingNodes` now treats any leaving element with a different DOM parent as a duplicate. If instance A is leaving in parent P1 and another instance of the same template is inserted into P2, A's leave animation is cut short. This happens for lists of components or embedded views that each have `animate.leave` and sit in different hosts. `animationend` is dispatched with `cancel: true` and A is removed immediately, which is a regression for unrelated instances. The overlay heuristic is too broad for this.
1. `packages/core/src/render3/node_animations.ts:54` (low, conf 0.25): The code that removed queued enter animations from the animation queue when a node is detached has been deleted, as has `removeAnimationsFromQueue`. If an element is created and then removed before the queue is flushed, its enter animation functions still run against a detached element. This can cause errors or stale animation state on removed nodes. Nothing else cancels those queued functions.

**Judge:** matched [0]: Finding 0 identifies the same defect. It notes that "`leavingNodes` is keyed by `tNode`, which is shared by every instance" and that the different-parent check cancels leave animations of unrelated instances inserted into different hosts. This is exactly the known bug's mechanism. Finding 1 describes a different concern: removed queued enter animations.

**Your verdict:** ☐ agree ☐ disagree (note: ...)

## django/bug-78fac1b047 condition C

**Known bug:** To accept both str and bytes, the commit adds `password = force_str(password)` (and the same for salt) in `PBKDF2PasswordHasher.encode()` and `MD5PasswordHasher.encode()`. `force_str` decodes bytes as UTF-8, so a bytes password that is not valid UTF-8 (a perfectly valid password value) now raises `UnicodeDecodeError` instead of being hashed. Fixed by passing the password through unchanged in PBKDF2 (`pbkdf2()` accepts bytes) and hashing `force_bytes(salt) + force_bytes(password)` in MD5.

**Findings:**

0. `django/contrib/auth/hashers.py:328` (medium, conf 0.5): PBKDF2PasswordHasher.encode() now calls force_str(password) before pbkdf2(). A bytes password that is not valid UTF-8 now raises UnicodeDecodeError, for example make_password(b'\xff\xfe') or check_password(b'\xff', encoded). Before this change, pbkdf2() applied force_bytes() to the password and hashed the raw bytes without trouble. This regresses the default hasher, since it needlessly round-trips bytes through str. The password should stay as bytes, or be converted with force_bytes() only.

**Judge:** matched [0]: Finding 0 points at the `force_str(password)` call in PBKDF2PasswordHasher.encode(). It says a bytes password that is not valid UTF-8 now raises UnicodeDecodeError, and it proposes keeping the password as bytes. This is the same mechanism as the known bug and matches its fix. The finding does not mention MD5, but the defect it describes is the same.

**Your verdict:** ☐ agree ☐ disagree (note: ...)
