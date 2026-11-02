# backend/services/crypto.py
import json
import base64
import hashlib
from typing import Any, Dict, List, Union
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed
from cryptography.exceptions import InvalidSignature

def canonical_json(data: Any) -> str:
    """
    Produces deterministic canonical JSON (sorted keys, no whitespace separators).
    DECISION 6: Canonical JSON of all fields except tx_id.
    """
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True)

def canonical_json_bytes(data: Any) -> bytes:
    return canonical_json(data).encode('utf-8')

def sha256_hash(data: Union[str, bytes]) -> str:
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()

def compute_tx_id(block_data: Dict[str, Any]) -> str:
    """
    DECISION 6: Ledger block hash = SHA-256 of canonical JSON (sorted keys, no whitespace)
    of all fields except tx_id (and internal MongoDB _id).
    """
    block_copy = {k: v for k, v in block_data.items() if k not in ("tx_id", "_id")}
    return sha256_hash(canonical_json(block_copy))

def compute_merkle_root(leaves: List[str]) -> str:
    """
    Computes SHA-256 Merkle root over list of hex strings.
    Documented leaf order: [seller_signature, buyer_signature, payment_ref]
    Empty strings are represented as 64 zeros.
    """
    if not leaves:
        return "0" * 64
    
    current_hashes = [
        sha256_hash(leaf.encode('utf-8')) if leaf else ("0" * 64)
        for leaf in leaves
    ]

    while len(current_hashes) > 1:
        if len(current_hashes) % 2 == 1:
            current_hashes.append(current_hashes[-1])
        next_level = []
        for i in range(0, len(current_hashes), 2):
            combined = current_hashes[i] + current_hashes[i+1]
            next_level.append(sha256_hash(combined.encode('utf-8')))
        current_hashes = next_level

    return current_hashes[0]

def verify_signature(
    public_key_pem_or_b64: str,
    payload_bytes_or_str: Union[bytes, str],
    signature_b64_or_hex: str
) -> bool:
    """
    Verifies ECDSA P-256 signature using SHA-256.
    Accepts public keys in PEM or Base64 (SPKI/raw DER) format,
    and signatures in Base64 or Hex (IEEE P1363 or DER).
    """
    try:
        if isinstance(payload_bytes_or_str, str):
            payload_bytes = payload_bytes_or_str.encode('utf-8')
        else:
            payload_bytes = payload_bytes_or_str

        # Decode public key
        key_str = public_key_pem_or_b64.strip()
        if "BEGIN PUBLIC KEY" in key_str:
            pub_key = serialization.load_pem_public_key(key_str.encode('utf-8'))
        else:
            try:
                der_bytes = base64.b64decode(key_str)
                pub_key = serialization.load_der_public_key(der_bytes)
            except Exception:
                # Try raw uncompressed point or hex
                der_bytes = bytes.fromhex(key_str)
                pub_key = serialization.load_der_public_key(der_bytes)

        # Decode signature
        sig_str = signature_b64_or_hex.strip()
        try:
            sig_bytes = base64.b64decode(sig_str)
        except Exception:
            sig_bytes = bytes.fromhex(sig_str)

        # If raw 64-byte signature (r || s from WebCrypto P1363), convert to DER
        if len(sig_bytes) == 64:
            r = int.from_bytes(sig_bytes[:32], byteorder='big')
            s = int.from_bytes(sig_bytes[32:], byteorder='big')
            sig_bytes = ec.encode_dss_signature(r, s)

        pub_key.verify(
            sig_bytes,
            payload_bytes,
            ec.ECDSA(hashes.SHA256())
        )
        return True
    except (InvalidSignature, Exception):
        return False

def generate_test_ecdsa_keypair():
    """Generates an ECDSA P-256 keypair for testing."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    
    pub_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    return private_key, pub_pem, priv_pem

def sign_payload_with_private_key(private_key, payload_bytes: bytes) -> str:
    """Signs payload and returns base64 DER signature."""
    signature = private_key.sign(
        payload_bytes,
        ec.ECDSA(hashes.SHA256())
    )
    return base64.b64encode(signature).decode('utf-8')
