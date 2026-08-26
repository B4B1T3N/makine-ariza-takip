/* Çevrimdışı arıza kuyruğu.
 *
 * Korunan senaryo: operatör atölyede arızayı yazarken bağlantı kopuyor.
 * Kayıt tarayıcıda (IndexedDB) saklanır, bağlantı gelince gönderilir.
 *
 * Neden navigator.onLine'a güvenmiyoruz: fabrika kablosuzuna bağlı bir tablet
 * "çevrimiçi" görünür ama sunucuya erişemiyor olabilir. Bu yüzden gönderim
 * her zaman denenir; ağ hatası alınırsa kuyruğa düşülür.
 *
 * Kapsam: yalnızca YENİ KAYIT GİRİŞİ. Listeyi çevrimdışı görüntüleme ve durum
 * değiştirme kapsam dışıdır; onlar çift yönlü senkronizasyon ve ayrı bir
 * çakışma çözümü gerektirir.
 */
(function () {
  "use strict";

  var VT_ADI = "mat-kuyruk";
  var DEPO = "arizalar";

  // --- Yardımcılar --------------------------------------------------------
  function uuidUret() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    // Güvenli bağlam olmayan (düz http) kurulumlarda crypto.randomUUID yoktur.
    // Bu değer yalnızca mükerrer kaydı önlemek için kullanılır, gizli değildir.
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function csrfToken() {
    var etiket = document.querySelector('meta[name="csrf-token"]');
    return etiket ? etiket.content : "";
  }

  // --- IndexedDB ----------------------------------------------------------
  function vtAc() {
    return new Promise(function (coz, reddet) {
      if (!window.indexedDB) return reddet(new Error("IndexedDB yok"));
      var istek = indexedDB.open(VT_ADI, 1);
      istek.onupgradeneeded = function () {
        if (!istek.result.objectStoreNames.contains(DEPO)) {
          istek.result.createObjectStore(DEPO, { keyPath: "client_uuid" });
        }
      };
      istek.onsuccess = function () { coz(istek.result); };
      istek.onerror = function () { reddet(istek.error); };
    });
  }

  function islem(mod, isYap) {
    return vtAc().then(function (vt) {
      return new Promise(function (coz, reddet) {
        var t = vt.transaction(DEPO, mod);
        var sonuc = isYap(t.objectStore(DEPO));
        t.oncomplete = function () { coz(sonuc && sonuc.result); };
        t.onerror = function () { reddet(t.error); };
      });
    });
  }

  function kuyrugaEkle(kayit) { return islem("readwrite", function (d) { return d.put(kayit); }); }
  function kuyruktanSil(id)   { return islem("readwrite", function (d) { return d.delete(id); }); }
  function kuyruguOku()       { return islem("readonly",  function (d) { return d.getAll(); }); }

  // --- Ekran bildirimi ----------------------------------------------------
  function bilgiGoster(mesaj, tur) {
    var kutu = document.getElementById("kuyruk-bilgisi");
    if (!kutu) return;
    kutu.textContent = mesaj;
    kutu.className = "uyari " + (tur || "uyari-tonu");
    kutu.hidden = false;
  }

  function seridiGuncelle() {
    var serit = document.getElementById("cevrimdisi-serit");
    if (serit) serit.hidden = navigator.onLine;
  }

  // --- Gönderim -----------------------------------------------------------
  function gonder(kayit) {
    return fetch("/api/arizalar", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
      body: JSON.stringify(kayit),
      credentials: "same-origin",
    });
  }

  /* Kuyruğu boşaltır. Sunucu 4xx dönerse kayıt hatalıdır ve tekrar denemek
   * sonucu değiştirmez; kuyruktan çıkarılır, yoksa sonsuza dek dener. */
  function kuyruguBosalt() {
    return kuyruguOku().then(function (kayitlar) {
      if (!kayitlar || !kayitlar.length) return 0;

      var zincir = Promise.resolve();
      var gonderilen = 0;

      kayitlar.forEach(function (kayit) {
        zincir = zincir.then(function () {
          return gonder(kayit).then(function (yanit) {
            if (yanit.ok) {
              gonderilen += 1;
              return kuyruktanSil(kayit.client_uuid);
            }
            if (yanit.status >= 400 && yanit.status < 500 && yanit.status !== 401) {
              return kuyruktanSil(kayit.client_uuid);
            }
            // 401 veya 5xx: bir sonraki denemeye bırakılır.
          });
        }).catch(function () { /* ağ hatası: kuyrukta kalsın */ });
      });

      return zincir.then(function () {
        if (gonderilen > 0) {
          bilgiGoster(
            "Bekleyen " + gonderilen + " kayıt sunucuya gönderildi.",
            "basari"
          );
        }
        return gonderilen;
      });
    }).catch(function () { return 0; });
  }

  function bekleyenleriBildir() {
    kuyruguOku().then(function (kayitlar) {
      if (kayitlar && kayitlar.length) {
        bilgiGoster(
          "Gönderilmeyi bekleyen " + kayitlar.length + " kayıt var. " +
          "Bağlantı gelince otomatik gönderilecek.",
          "uyari-tonu"
        );
      }
    }).catch(function () {});
  }

  // --- Form yakalama ------------------------------------------------------
  function formuBagla() {
    var form = document.getElementById("ariza-formu");
    if (!form) return;

    form.addEventListener("submit", function (olay) {
      var dugme = form.querySelector('button[type="submit"]');
      var veri = new FormData(form);

      var kayit = {
        client_uuid: uuidUret(),
        makine_id: parseInt(veri.get("makine_id"), 10),
        baslik: (veri.get("baslik") || "").trim(),
        aciklama: (veri.get("aciklama") || "").trim(),
        oncelik: veri.get("oncelik") || "orta",
        // Arızanın yazıldığı an. Kayıt kuyrukta saatlerce beklese bile
        // çözüm süresi bu andan itibaren hesaplanır.
        olusma_zamani: new Date().toISOString(),
      };

      if (!kayit.makine_id || !kayit.baslik) return;  // Tarayıcı doğrulaması halletsin.

      olay.preventDefault();
      if (dugme) { dugme.disabled = true; dugme.textContent = "Gönderiliyor..."; }

      gonder(kayit).then(function (yanit) {
        if (yanit.status === 401) { window.location = "/giris"; return; }

        return yanit.json().then(function (govde) {
          if (yanit.ok) {
            window.location = govde.adres || "/arizalar";
            return;
          }
          bilgiGoster(govde.hata || "Kayıt gönderilemedi.", "hata");
          if (dugme) { dugme.disabled = false; dugme.textContent = "Kaydı aç"; }
        });
      }).catch(function () {
        // Ağ hatası: kayıt cihazda saklanır.
        kuyrugaEkle(kayit).then(function () {
          form.reset();
          bilgiGoster(
            "Bağlantı yok. Kayıt cihazınıza alındı ve bağlantı gelince " +
            "otomatik gönderilecek. Bu sekmeyi kapatabilirsiniz.",
            "uyari-tonu"
          );
        }).catch(function () {
          bilgiGoster(
            "Bağlantı yok ve kayıt cihaza da yazılamadı. " +
            "Lütfen bilgileri not edip bağlantı gelince tekrar girin.",
            "hata"
          );
        }).then(function () {
          if (dugme) { dugme.disabled = false; dugme.textContent = "Kaydı aç"; }
        });
      });
    });
  }

  // --- Service worker -----------------------------------------------------
  function servisiKaydet() {
    // Service worker yalnızca güvenli bağlamda (HTTPS veya localhost) çalışır.
    // Düz http ile LAN'da sunulduğunda kayıt sessizce atlanır; kuyruk yine
    // çalışır, ama sayfanın kendisi çevrimdışı açılmaz.
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }

  // --- Başlangıç ----------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    seridiGuncelle();
    formuBagla();
    servisiKaydet();
    bekleyenleriBildir();
    if (navigator.onLine) kuyruguBosalt();
  });

  window.addEventListener("online", function () {
    seridiGuncelle();
    kuyruguBosalt();
  });
  window.addEventListener("offline", seridiGuncelle);
})();
