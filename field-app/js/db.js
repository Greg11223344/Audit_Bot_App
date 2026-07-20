// Minimal IndexedDB wrapper -- no external libraries (no build tooling on this machine).
const DB_NAME = "audit_bot_field";
const DB_VERSION = 1;

let dbPromise = null;

function openDb() {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onupgradeneeded = () => {
      const db = req.result;

      if (!db.objectStoreNames.contains("audits")) {
        db.createObjectStore("audits", { keyPath: "client_uuid" });
      }
      if (!db.objectStoreNames.contains("attachments")) {
        db.createObjectStore("attachments", { keyPath: "client_uuid" });
      }
      if (!db.objectStoreNames.contains("catalog")) {
        db.createObjectStore("catalog", { keyPath: "key" });
      }
      if (!db.objectStoreNames.contains("session")) {
        db.createObjectStore("session", { keyPath: "key" });
      }
    };

    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  return dbPromise;
}

async function tx(storeName, mode) {
  const db = await openDb();
  return db.transaction(storeName, mode).objectStore(storeName);
}

function wrap(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

export const DB = {
  async put(storeName, value) {
    const store = await tx(storeName, "readwrite");
    return wrap(store.put(value));
  },
  async get(storeName, key) {
    const store = await tx(storeName, "readonly");
    return wrap(store.get(key));
  },
  async delete(storeName, key) {
    const store = await tx(storeName, "readwrite");
    return wrap(store.delete(key));
  },
  async getAll(storeName) {
    const store = await tx(storeName, "readonly");
    return wrap(store.getAll());
  },
};
