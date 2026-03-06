// Copyright (c) Meta Platforms, Inc. and affiliates.
// Optimized global cache with parallel-hashmap for better cache locality

#pragma once

#include "cinderx/python.h"

#ifdef __cplusplus

#include "cinderx/Common/ref.h"
#include "cinderx/Common/slab_arena.h"
#include "cinderx/Jit/global_cache_iface.h"

#ifdef Py_GIL_DISABLED
#include <mutex>
#endif
#include <parallel_hashmap/phmap.h>
#include <vector>

namespace jit {

// Cache line size for alignment optimization
constexpr size_t kCacheLineSize = 64;

// Identifies a cached global Python value.
struct GlobalCacheKey {
  // builtins and globals are weak references; the invalidation code is
  // responsible for erasing any relevant keys when a dict is freed.
  BorrowedRef<PyDictObject> builtins;
  BorrowedRef<PyDictObject> globals;
  Ref<PyUnicodeObject> name;

  GlobalCacheKey(
      BorrowedRef<PyDictObject> builtins,
      BorrowedRef<PyDictObject> globals,
      BorrowedRef<PyUnicodeObject> name);

  ~GlobalCacheKey();

  GlobalCacheKey(const GlobalCacheKey&) = delete;
  GlobalCacheKey& operator=(const GlobalCacheKey&) = delete;
  
  GlobalCacheKey(GlobalCacheKey&& other) noexcept
      : builtins(other.builtins), globals(other.globals), name(std::move(other.name)) {
    other.builtins = nullptr;
    other.globals = nullptr;
  }
  
  GlobalCacheKey& operator=(GlobalCacheKey&& other) noexcept {
    if (this != &other) {
      builtins = other.builtins;
      globals = other.globals;
      name = std::move(other.name);
      other.builtins = nullptr;
      other.globals = nullptr;
    }
    return *this;
  }

  bool operator==(const GlobalCacheKey& other) const = default;
};

struct GlobalCacheKeyHash {
  std::size_t operator()(const GlobalCacheKey& key) const;
};

// Use phmap::flat_hash_map for better cache locality
// This uses open addressing with SIMD optimizations
using GlobalCacheMap = phmap::flat_hash_map<GlobalCacheKey, PyObject**, GlobalCacheKeyHash>;

// Wrapper class to initialize, update, and disable a global cache.
class GlobalCache {
 public:
  explicit GlobalCache(GlobalCacheMap::value_type* pair) : pair_(pair) {}

  const GlobalCacheKey& key() const { return pair_->first; }
  PyObject** valuePtr() const { return pair_->second; }
  void init(PyObject** cache) const { pair_->second = cache; }
  void clear() { *valuePtr() = nullptr; }

  bool operator<(const GlobalCache& other) const {
    return pair_ < other.pair_;
  }

 private:
  GlobalCacheMap::value_type* pair_;
};

// Optimized watch map using flat_hash_map
// Key: (dict, name) pair, Value: vector of watchers
struct DictKeyPair {
  BorrowedRef<PyDictObject> dict;
  BorrowedRef<PyUnicodeObject> name;
  
  bool operator==(const DictKeyPair& other) const {
    return dict == other.dict && name == other.name;
  }
};

struct DictKeyPairHash {
  std::size_t operator()(const DictKeyPair& key) const {
    std::hash<PyObject*> hasher;
    return hasher(key.dict) ^ (hasher(key.name) << 1);
  }
};

// Optimized watch map with flat_hash_map for better cache locality
using WatchMapInner = phmap::flat_hash_map<DictKeyPair, std::vector<GlobalCache>, DictKeyPairHash>;

// Manages all memory and data structures for global cache values.
class GlobalCacheManager : public IGlobalCacheManager {
 public:
  ~GlobalCacheManager() override;

  PyObject** getGlobalCache(
      BorrowedRef<PyDictObject> builtins,
      BorrowedRef<PyDictObject> globals,
      BorrowedRef<PyUnicodeObject> key) override;

  void notifyDictUpdate(
      BorrowedRef<PyDictObject> dict,
      BorrowedRef<PyUnicodeObject> key,
      BorrowedRef<> value) override;

  void notifyDictClear(BorrowedRef<PyDictObject> dict) override;

  void notifyDictUnwatch(BorrowedRef<PyDictObject> dict) override;

  void clear() override;

 private:
  GlobalCache findGlobalCache(
      BorrowedRef<PyDictObject> builtins,
      BorrowedRef<PyDictObject> globals,
      BorrowedRef<PyUnicodeObject> key);

  bool isWatchedDictKey(
      BorrowedRef<PyDictObject> dict,
      BorrowedRef<PyUnicodeObject> key,
      GlobalCache cache);

  void watchDictKey(
      BorrowedRef<PyDictObject> dict,
      BorrowedRef<PyUnicodeObject> key,
      GlobalCache cache);

  void unwatchDictKey(
      BorrowedRef<PyDictObject> dict,
      BorrowedRef<PyUnicodeObject> key,
      GlobalCache cache);

  void initCache(GlobalCache cache);

  [[nodiscard]] bool updateCache(
      GlobalCache cache,
      BorrowedRef<PyDictObject> dict,
      BorrowedRef<> new_value);

  void disableCaches(const std::vector<GlobalCache>& caches);
  void disableCache(GlobalCache cache);

  // Arena where all the global value caches are allocated.
  SlabArena<PyObject*> arena_;

#ifdef Py_GIL_DISABLED
  std::recursive_mutex mutex_;
#endif

  // Optimized flat_hash_map for global caches - better cache locality
  GlobalCacheMap map_;

  // Optimized watch map using flat_hash_map
  WatchMapInner watch_map_;
};

} // namespace jit

#endif
