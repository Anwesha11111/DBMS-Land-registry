// scripts/mongo_init.js: MongoDB initialization script
// Sets up ledger_transaction_block collection with JSON schema validation, unique indexes,
// and dedicated app user with insert + find permissions only (no update, no delete).

db = db.getSiblingDB('landregistry');

// 1. Create collection with strict JSON-schema validator
db.createCollection('ledger_transaction_block', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: [
        'tx_id',
        'block_number',
        'prev_tx_hash',
        'block_type',
        'registry_id',
        'plot_id',
        'timestamp',
        'merkle_root',
        'nonce'
      ],
      properties: {
        tx_id: {
          bsonType: 'string',
          pattern: '^[a-f0-9]{64}$',
          description: 'SHA-256 hash of canonical JSON block data (excluding tx_id)'
        },
        block_number: {
          bsonType: ['int', 'long', 'double'],
          minimum: 0,
          description: 'Sequential block height starting at 0'
        },
        prev_tx_hash: {
          bsonType: 'string',
          pattern: '^[a-f0-9]{64}$',
          description: 'SHA-256 hash of previous block (64 zeros for Genesis)'
        },
        block_type: {
          enum: ['GENESIS', 'SALE', 'CORRECTION'],
          description: 'Allowed transaction block types'
        },
        registry_id: {
          bsonType: 'string',
          description: 'Unique registry entry ID'
        },
        plot_id: {
          bsonType: 'string',
          description: 'Unique plot identifier'
        },
        seller_id: {
          bsonType: ['string', 'null'],
          description: 'Owner ID of seller (null for Genesis)'
        },
        buyer_id: {
          bsonType: 'string',
          description: 'Owner ID of buyer / initial title holder'
        },
        sale_price: {
          bsonType: ['double', 'int', 'long', 'decimal', 'null'],
          description: 'Settled transaction price'
        },
        timestamp: {
          bsonType: 'string',
          description: 'ISO-8601 formatted canonical timestamp'
        },
        merkle_root: {
          bsonType: 'string',
          pattern: '^[a-f0-9]{64}$',
          description: 'SHA-256 Merkle root of signatures and payment reference'
        },
        nonce: {
          bsonType: ['int', 'long', 'double'],
          description: 'Fixed at 0 for spec compliance'
        },
        seller_signature: {
          bsonType: ['string', 'null'],
          description: 'ECDSA P-256 signature from seller'
        },
        buyer_signature: {
          bsonType: ['string', 'null'],
          description: 'ECDSA P-256 signature from buyer'
        },
        gid: {
          bsonType: ['string', 'null'],
          description: 'PostgreSQL 2PC prepared transaction GID'
        },
        corrects_tx_id: {
          bsonType: ['string', 'null'],
          description: 'Reference to original block tx_id for CORRECTION blocks'
        },
        approved_by: {
          bsonType: ['string', 'null'],
          description: 'Second approver ID for CORRECTION blocks'
        }
      }
    }
  }
});

// 2. Unique Indexes to guarantee append-only immutability and prevent forks
db.ledger_transaction_block.createIndex({ block_number: 1 }, { unique: true });
db.ledger_transaction_block.createIndex({ prev_tx_hash: 1 }, { unique: true });
db.ledger_transaction_block.createIndex({ plot_id: 1, block_number: 1 });
db.ledger_transaction_block.createIndex({ tx_id: 1 }, { unique: true });
db.ledger_transaction_block.createIndex({ gid: 1 }, { sparse: true });

// 3. Create custom read-write role with insert + find ONLY (no update, no delete)
db.createRole({
  role: 'ledgerAppRole',
  privileges: [
    {
      resource: { db: 'landregistry', collection: 'ledger_transaction_block' },
      actions: ['find', 'insert']
    }
  ],
  roles: []
});

// 4. Create the application user restricted to insert + find only
db.createUser({
  user: 'land_app',
  pwd: 'ledger_secret_pass',
  roles: [
    { role: 'ledgerAppRole', db: 'landregistry' }
  ]
});

print('MongoDB Land Exchange Ledger initialization complete.');
