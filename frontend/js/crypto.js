/**
 * frontend/js/crypto.js
 * In-browser WebCrypto ECDSA P-256 signing module.
 * DECISION 7: Private keys are generated and used only in the browser (ECDSA P-256).
 * Server stores public keys and verifies signatures. Private keys reside in IndexedDB
 * or local storage and are never transmitted over the network.
 */

// Helper to convert ArrayBuffer to Base64
export function bufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

// Helper to convert Base64 to ArrayBuffer
export function base64ToBuffer(base64) {
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

// Convert raw WebCrypto signature (r || s, 64 bytes) to ASN.1 DER format
export function p1363ToDer(rawSig) {
  const rawBytes = new Uint8Array(rawSig);
  if (rawBytes.length !== 64) {
    return rawSig; // Already DER or unexpected
  }
  
  function trimAndPad(bytes) {
    let start = 0;
    while (start < bytes.length && bytes[start] === 0) start++;
    if (start === bytes.length) return new Uint8Array([0]);
    if (bytes[start] & 0x80) {
      const padded = new Uint8Array(bytes.length - start + 1);
      padded[0] = 0;
      padded.set(bytes.subarray(start), 1);
      return padded;
    }
    return bytes.subarray(start);
  }

  const r = trimAndPad(rawBytes.subarray(0, 32));
  const s = trimAndPad(rawBytes.subarray(32, 64));

  const totalLen = 2 + r.length + 2 + s.length;
  const der = new Uint8Array(2 + totalLen);
  der[0] = 0x30; // SEQUENCE
  der[1] = totalLen;
  der[2] = 0x02; // INTEGER
  der[3] = r.length;
  der.set(r, 4);
  const sOffset = 4 + r.length;
  der[sOffset] = 0x02; // INTEGER
  der[sOffset + 1] = s.length;
  der.set(s, sOffset + 2);

  return der.buffer;
}

/**
 * Generates an ECDSA P-256 key pair using the standard WebCrypto API.
 */
export async function generateKeyPair() {
  const keyPair = await window.crypto.subtle.generateKey(
    {
      name: "ECDSA",
      namedCurve: "P-256"
    },
    true, // extractable for backup/IndexedDB export
    ["sign", "verify"]
  );
  return keyPair;
}

/**
 * Exports the public key as a PEM formatted string for server registration.
 */
export async function exportPublicKey(keyPair) {
  const spkiBuffer = await window.crypto.subtle.exportKey("spki", keyPair.publicKey);
  const b64 = bufferToBase64(spkiBuffer);
  // Format as standard PEM
  const pem = `-----BEGIN PUBLIC KEY-----\n${b64.match(/.{1,64}/g).join('\n')}\n-----END PUBLIC KEY-----`;
  return pem;
}

/**
 * Produces deterministic canonical JSON (sorted keys, no extra whitespace).
 */
export function canonicalJson(data) {
  if (data === null || typeof data !== "object") {
    return JSON.stringify(data);
  }
  if (Array.isArray(data)) {
    return "[" + data.map(canonicalJson).join(",") + "]";
  }
  const keys = Object.keys(data).sort();
  const entries = keys.map(k => `${JSON.stringify(k)}:${canonicalJson(data[k])}`);
  return "{" + entries.join(",") + "}";
}

/**
 * Signs payload data with private key using ECDSA SHA-256.
 * Returns Base64-encoded ASN.1 DER signature suitable for Python cryptography verification.
 */
export async function signPayload(privateKey, payloadObject) {
  const canonicalStr = canonicalJson(payloadObject);
  const encoder = new TextEncoder();
  const dataBytes = encoder.encode(canonicalStr);

  const rawSignature = await window.crypto.subtle.sign(
    {
      name: "ECDSA",
      hash: { name: "SHA-256" }
    },
    privateKey,
    dataBytes
  );

  const derSignature = p1363ToDer(rawSignature);
  return bufferToBase64(derSignature);
}

/**
 * IndexedDB storage utilities to ensure private keys remain local to browser.
 */
const DB_NAME = "LandExchangeKeyStore";
const STORE_NAME = "keys";

function openKeyDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(STORE_NAME);
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function savePrivateKey(userId, privateKey) {
  const db = await openKeyDB();
  const jwk = await window.crypto.subtle.exportKey("jwk", privateKey);
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readwrite");
    tx.objectStore(STORE_NAME).put(jwk, userId);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export async function loadPrivateKey(userId) {
  const db = await openKeyDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, "readonly");
    const req = tx.objectStore(STORE_NAME).get(userId);
    req.onsuccess = async () => {
      if (!req.result) return resolve(null);
      const key = await window.crypto.subtle.importKey(
        "jwk",
        req.result,
        { name: "ECDSA", namedCurve: "P-256" },
        true,
        ["sign"]
      );
      resolve(key);
    };
    req.onerror = () => reject(req.error);
  });
}
