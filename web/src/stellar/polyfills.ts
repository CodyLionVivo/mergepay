/**
 * `Buffer` global para stellar-sdk en el navegador.
 *
 * El SDK importa el polyfill `buffer` por su cuenta, pero una de sus
 * dependencias (`base32.js`, que usa `StrKey.decode*`) lee el `Buffer` global.
 * Sin esto, `new Contract()`, `new Address()` o `getAccount()` fallan en el
 * navegador con "Buffer is not defined". Tiene que importarse antes que el SDK.
 */

import { Buffer } from 'buffer'

const scope = globalThis as { Buffer?: typeof Buffer }

if (scope.Buffer === undefined) {
  scope.Buffer = Buffer
}
