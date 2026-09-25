# UI translations

English is the default. `en.ts` contains readable English source keys and `es.ts`
provides the matching Spanish copy, checked by TypeScript.

Use `const { t } = useI18n()` in new components. Existing components subscribe
with `useI18n()` and call the exported `t`. Translation happens at render time,
including validation errors and labels stored in lookup tables. The external
store updates mounted components without resetting forms or transaction state.

Use placeholders for variable labels: `t('Remove criterion {number}', { number })`.
Never translate bounty titles, descriptions, acceptance text, repository names,
addresses, hashes, signed messages, or protocol state identifiers. Unknown server
diagnostics fall back to their original text. Dates follow the selected language
and the browser's time zone; amounts sent to the API retain their existing format.

The selector persists `mergepay.language` in localStorage, tolerates unavailable
storage, and updates the document language. No translation or styling dependency
is required.
