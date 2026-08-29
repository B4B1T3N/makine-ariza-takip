/* Sayfa içi küçük etkileşimler.
 *
 * Bu kod, HTML'in içindeki `onclick`/`onsubmit` özniteliklerinin yerine
 * geçer. Sebebi Faz 5'te eklenen içerik güvenliği politikasıdır (CSP):
 * satır içi betiğe izin verilmemesi, saldırganın sayfaya kod
 * enjekte etmesini zorlaştıran ucuz ve etkili bir önlemdir. Aynı davranış
 * burada, tek yerde ve olay devriyle sağlanır.
 */
(function () {
  "use strict";

  // Tablo satırının tamamı tıklanabilir. Satırın içindeki bağlantı, düğme
  // veya form öğesine tıklandıysa karışılmaz — kullanıcı onu istemiştir.
  document.addEventListener("click", function (olay) {
    var tiklanan = olay.target;
    if (tiklanan.closest("a, button, input, select, textarea, label")) {
      return;
    }
    var satir = tiklanan.closest("[data-adres]");
    if (satir) {
      window.location = satir.getAttribute("data-adres");
    }
  });

  // Geri alınamayan işlemler (dosya silme, bildirimleri temizleme) onay ister.
  document.addEventListener(
    "submit",
    function (olay) {
      var form = olay.target;
      var mesaj = form.getAttribute && form.getAttribute("data-onay");
      if (mesaj && !window.confirm(mesaj)) {
        olay.preventDefault();
      }
    },
    true
  );
})();
