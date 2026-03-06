// Copyright (c) Meta Platforms, Inc. and affiliates.
// Optimized global cache implementation with parallel-hashmap

#include "cinderx/Jit/global_cache_optimized.h"

#include "cinderx/Common/dict.h"
#include "cinderx/Common/util.h"
#include "cinderx/Common/watchers.h"
#include "cinderx/Jit/threaded_compile.h"
#include "cinderx/module_state.h"

#include <algorithm>

#ifndef ENABLE_LAZY_IMPORTS
#ifdef PyLazyImport_CheckExact
#undef PyLazyImport_CheckExact
#endif
#define PyLazyImport_CheckExact(OBJ) false
#endif

namespace jit {

// ============================================================================
// GlobalCacheKey Implementation
// ============================================================================

GlobalCacheKey::GlobalCacheKey(
    BorrowedRef<PyDictObject> builtins,
    BorrowedRef<PyDictObject> globals,
    BorrowedRef<PyUnicodeObject> name)
    : builtins{builtins}, globals{globals} {
  ThreadedCompileSerialize guard;
  JIT_CHECK(
      PyUnicode_CHECK_INTERNED(name.get()),
      "Global cache names must be interned; they'll be compared by pointer "
      "value");
  this->name = Ref<>::create(name);
}

GlobalCacheKey::~GlobalCacheKey() {
  ThreadedCompileSerialize guard;
  name.reset();
}

std::size_t GlobalCacheKeyHash::operator()(const GlobalCacheKey& key) const {
  std::hash<PyObject*> hasher;
  return combineHash(
      hasher(key.builtins), hasher(key.globals), hasher(key.name));
}

// ============================================================================
// GlobalCacheManager Implementation
// ============================================================================

GlobalCacheManager::~GlobalCacheManager() {
  clear();
}

GlobalCache GlobalCacheManager::findGlobalCache(
    BorrowedRef<PyDictObject> builtins,
    BorrowedRef<PyDictObject> globals,
    BorrowedRef<PyUnicodeObject> key) {
  // Use emplace with piecewise_construct for in-place construction
  auto result = map_.emplace(
      std::piecewise_construct,
      std::forward_as_tuple(builtins, globals, key),
      std::forward_as_tuple());
  
  GlobalCache cache(&*result.first);

  // This is a new global cache entry, so we have to initialize it.
  if (result.second) {
    initCache(cache);
  }

  return cache;
}

PyObject** GlobalCacheManager::getGlobalCache(
    BorrowedRef<PyDictObject> builtins,
    BorrowedRef<PyDictObject> globals,
    BorrowedRef<PyUnicodeObject> key) {
  try {
#ifdef Py_GIL_DISABLED
    std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
    auto cache = findGlobalCache(builtins, globals, key);
    return cache.valuePtr();
  } catch (std::bad_alloc&) {
    return nullptr;
  }
}

void GlobalCacheManager::notifyDictUpdate(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    BorrowedRef<> value) {
  JIT_CHECK(
      PyUnicode_CHECK_INTERNED(key.get()),
      "Dict key must be interned as it'll be compared by pointer value");

#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif

  DictKeyPair pair{dict, key};
  auto it = watch_map_.find(pair);
  if (it == watch_map_.end()) {
    return;
  }
  
  // Copy watchers to avoid modification during iteration
  std::vector<GlobalCache> watchers_copy = it->second;
  
  std::vector<GlobalCache> to_disable;
  for (GlobalCache cache : watchers_copy) {
    if (updateCache(cache, dict, value)) {
      to_disable.emplace_back(cache);
    }
  }
  disableCaches(to_disable);
}

void GlobalCacheManager::notifyDictClear(BorrowedRef<PyDictObject> dict) {
#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif

  // Collect all caches that need to be updated
  std::vector<GlobalCache> to_disable;
  
  // Iterate through watch_map_ to find entries for this dict
  for (auto it = watch_map_.begin(); it != watch_map_.end(); ++it) {
    if (it->first.dict == dict) {
      for (GlobalCache cache : it->second) {
        if (updateCache(cache, dict, nullptr)) {
          to_disable.emplace_back(cache);
        }
      }
    }
  }
  
  disableCaches(to_disable);
}

void GlobalCacheManager::notifyDictUnwatch(BorrowedRef<PyDictObject> dict) {
#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif

  std::vector<GlobalCache> to_disable;
  std::vector<DictKeyPair> to_remove;

  // Find all watch entries for this dict
  for (auto it = watch_map_.begin(); it != watch_map_.end(); ++it) {
    if (it->first.dict == dict) {
      for (auto cache : it->second) {
        // Unsubscribe from the corresponding globals/builtins dict if needed.
        PyObject* globals = cache.key().globals;
        PyObject* builtins = cache.key().builtins;
        if (globals != builtins) {
          if (dict == globals) {
            // when shutting down builtins goes away and we won't be
            // watching builtins if the value we are watching was defined
            // globally at the module level but was never deleted.
            if (isWatchedDictKey(builtins, cache.key().name, cache)) {
              unwatchDictKey(builtins, cache.key().name, cache);
            }
          } else {
            unwatchDictKey(globals, cache.key().name, cache);
          }
        }

        to_disable.emplace_back(cache);
      }
      to_remove.push_back(it->first);
    }
  }
  
  // Remove watch entries
  for (const auto& pair : to_remove) {
    watch_map_.erase(pair);
  }
  
  for (GlobalCache cache : to_disable) {
    disableCache(cache);
  }
}

void GlobalCacheManager::clear() {
  std::vector<PyObject*> keys;
#ifdef Py_GIL_DISABLED
  std::lock_guard<std::recursive_mutex> lock(mutex_);
#endif
  
  // Collect all unique dicts from watch_map_
  phmap::flat_hash_set<BorrowedRef<PyDictObject>> dicts;
  for (const auto& pair : watch_map_) {
    dicts.insert(pair.first.dict);
  }
  
  for (auto dict : dicts) {
    notifyDictUnwatch(dict);
    cinderx::getModuleState()->watcherState().unwatchDict(dict);
  }
}

bool GlobalCacheManager::isWatchedDictKey(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    GlobalCache cache) {
  DictKeyPair pair{dict, key};
  auto it = watch_map_.find(pair);
  if (it == watch_map_.end()) {
    return false;
  }
  
  const auto& watchers = it->second;
  return std::find(watchers.begin(), watchers.end(), cache) != watchers.end();
}

void GlobalCacheManager::watchDictKey(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    GlobalCache cache) {
  DictKeyPair pair{dict, key};
  auto& watchers = watch_map_[pair];
  watchers.push_back(cache);
  
  JIT_CHECK(
      cinderx::getModuleState()->watcherState().watchDict(dict) == 0,
      "Failed to watch globals or builtins dict");
}

void GlobalCacheManager::unwatchDictKey(
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<PyUnicodeObject> key,
    GlobalCache cache) {
  DictKeyPair pair{dict, key};
  auto it = watch_map_.find(pair);
  if (it == watch_map_.end()) {
    return;
  }
  
  auto& watchers = it->second;
  auto cache_it = std::find(watchers.begin(), watchers.end(), cache);
  if (cache_it != watchers.end()) {
    watchers.erase(cache_it);
  }
  
  if (watchers.empty()) {
    watch_map_.erase(it);
    
    // Check if dict has any more watchers
    bool has_more = false;
    for (const auto& p : watch_map_) {
      if (p.first.dict == dict) {
        has_more = true;
        break;
      }
    }
    
    if (!has_more) {
      cinderx::getModuleState()->watcherState().unwatchDict(dict);
    }
  }
}

void GlobalCacheManager::initCache(GlobalCache cache) {
  cache.init(arena_.allocate());

  BorrowedRef<PyDictObject> globals = cache.key().globals;
  BorrowedRef<PyDictObject> builtins = cache.key().builtins;
  BorrowedRef<PyUnicodeObject> key = cache.key().name;

  JIT_DCHECK(
      hasOnlyUnicodeKeys(globals),
      "Should have already checked that globals dict was watchable");

  // We want to try and only watch builtins if this is really a builtin.  So we
  // will start only watching globals, and if the value gets deleted from
  // globals then we'll start tracking builtins as well.  Once we start tracking
  // builtins we'll never stop rather than trying to handle all of the
  // transitions.
  watchDictKey(globals, key, cache);

  // We don't need to immediately watch builtins if the value is found in
  // globals.
  if ([[maybe_unused]] PyObject* globals_value = PyDict_GetItem(globals, key)) {
    // The dict getitem could have triggered a lazy import with side effects
    // that unwatched the dict.
#ifdef ENABLE_LAZY_IMPORTS
    if (cache.valuePtr())
#endif
    {
      *cache.valuePtr() = globals_value;
    }
    return;
  }

  // The getitem on globals might have had side effects and made this dict
  // unwatchable, so it needs to be checked again.
  if (hasOnlyUnicodeKeys(builtins)) {
    *cache.valuePtr() = PyDict_GetItem(builtins, key);
    if (globals != builtins) {
      watchDictKey(builtins, key, cache);
    }
  }
}

bool GlobalCacheManager::updateCache(
    GlobalCache cache,
    BorrowedRef<PyDictObject> dict,
    BorrowedRef<> new_value) {
  if (new_value && PyLazyImport_CheckExact(new_value)) {
    return true;
  }

  BorrowedRef<PyDictObject> globals = cache.key().globals;
  BorrowedRef<PyDictObject> builtins = cache.key().builtins;
  BorrowedRef<PyUnicodeObject> name = cache.key().name;

  if (dict == globals) {
    if (new_value == nullptr && globals != builtins) {
      if (!hasOnlyUnicodeKeys(builtins)) {
        // builtins is no longer watchable. Mark this cache for disabling.
        return true;
      }

      // Fall back to the builtin (which may also be null).
      *cache.valuePtr() = PyDict_GetItem(builtins, name);

      // it changed, and it changed from something to nothing, so
      // we weren't watching builtins and need to start now.
      if (!isWatchedDictKey(builtins, name, cache)) {
        watchDictKey(builtins, name, cache);
      }
    } else {
      *cache.valuePtr() = new_value;
    }
  } else {
    JIT_CHECK(dict == builtins, "Unexpected dict");
    JIT_CHECK(hasOnlyUnicodeKeys(globals), "Bad globals dict");
    // Check if this value is shadowed.
    PyObject* globals_value = PyDict_GetItem(globals, name);
    if (globals_value == nullptr) {
      *cache.valuePtr() = new_value;
    }
  }

  return false;
}

void GlobalCacheManager::disableCache(GlobalCache cache) {
  cache.clear();
  map_.erase(cache.key());
}

void GlobalCacheManager::disableCaches(const std::vector<GlobalCache>& caches) {
  for (GlobalCache cache : caches) {
    BorrowedRef<PyDictObject> dict = cache.key().globals;
    BorrowedRef<PyUnicodeObject> name = cache.key().name;
    disableCache(cache);
    unwatchDictKey(dict, name, cache);
  }
}

} // namespace jit
