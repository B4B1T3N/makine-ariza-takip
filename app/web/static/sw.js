/* Service worker — çevrimdışıyken yeni kayıt sayfasının açılabilmesi için.
 *
 * Kapsam bilinçli olarak dar: yalnızca "Yeni Arıza" formu ve statik
 * dosyalar önbelleğe alınır. Arıza listesi ve detay sayfaları önbelleğe
 * ALINMAZ — bayat bir liste, teknisyene kaydın gerçek durumunu yanlış
 * gösterir ve bu, sayfanın hiç açılmamasından daha kötüdür.
 */

var ONBELLEK = "mat-v1";

var ONCEDEN_ALINACAKLAR = [
  "/arizalar/yeni",
  "/static/app.css",
  "/static/kuyruk.js",
  "/cevrimdisi",
];

self.addEventListener("install", function (olay) {
  olay.waitUntil(
    caches.open(ONBELLEK).then(function (onbellek) {
      // Tek bir dosya alınamazsa kurulumun tamamı düşmesin.
      return Promise.all(
        ONCEDEN_ALINACAKLAR.map(function (adres) {
          return onbellek.add(adres).catch(function () {});
        })
      );
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (olay) {
  olay.waitUntil(
    caches.keys().then(function (adlar) {
      return Promise.all(
        adlar.filter(function (ad) { return ad !== ONBELLEK; })
             .map(function (ad) { return caches.delete(ad); })
      );
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (olay) {
  var istek = olay.request;

  // Yazma istekleri asla önbellekten karşılanmaz; kuyruk mantığı kuyruk.js'te.
  if (istek.method !== "GET") return;

  var adres = new URL(istek.url);
  if (adres.origin !== self.location.origin) return;
  if (adres.pathname.startsWith("/api/")) return;

  // Statik dosyalar: önce önbellek (sürüm değişince ONBELLEK adı değişir).
  if (adres.pathname.startsWith("/static/")) {
    olay.respondWith(
      caches.match(istek).then(function (bulunan) {
        return bulunan || fetch(istek).then(function (yanit) {
          var kopya = yanit.clone();
          caches.open(ONBELLEK).then(function (o) { o.put(istek, kopya); });
          return yanit;
        });
      })
    );
    return;
  }

  // Yeni kayıt sayfası: önce ağ, başarısızsa önbellekteki son sürüm.
  // Makine listesi sayfanın içinde geldiği için form çevrimdışı da doldurulur.
  if (adres.pathname === "/arizalar/yeni") {
    olay.respondWith(
      fetch(istek).then(function (yanit) {
        var kopya = yanit.clone();
        caches.open(ONBELLEK).then(function (o) { o.put(istek, kopya); });
        return yanit;
      }).catch(function () {
        return caches.match(istek).then(function (bulunan) {
          return bulunan || caches.match("/cevrimdisi");
        });
      })
    );
    return;
  }

  // Diğer sayfalar: yalnızca ağ. Erişilemiyorsa açıklayıcı çevrimdışı sayfası.
  if (istek.mode === "navigate") {
    olay.respondWith(
      fetch(istek).catch(function () {
        return caches.match("/cevrimdisi");
      })
    );
  }
});
