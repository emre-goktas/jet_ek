Projemin kullanım kurgusunu şöyle tasarlamak istiyorum;

1- Kullanıcı domaini tarayıcıya girer.(örnek www.jetek.com)
2- Kullanıcı gmail hesapıyla şifresiz giriş yapar. Jetek açılınca kullanıcının ilk göreceği şey, google gmail ile giriş yap ekranı olur. Kullanıcı gmail ile hemen girer.
3- Kayıt ekranımız(henüz tasarlamadık) açılır ve kullanıcı bilgilerini kaydederiz. Bu bilgiler; isim soyisim, unvan ve şablon seçimi(word şablonu) gibi bilgiler olur ve bu bilgileri sqlite a kaydederiz. Kayıt ekranımız için arayüzde bir kullanıcı profili oluşturacağız. Bu profil, kullanıcının şablonu ve diğer bilgilerini tutar. İstediği zaman değiştirebilir. Değişiklik durumdan veritabanımız güncellenmeli. Kullanıcının boş bırakamayacağı tek alan şablon seçimi olacak. şuan temel olarak 3 adet şablonumuz var. 
1- sgk_template(bunun isimi sgk müfettiş şablonu yapcam)
2- henüz proje dizininde yok ama sgk_template ile %100 uyumlu oan bir sgk denetmen şablonu docx dosyası ekleyeğim. bu şablon seçilirse ekstra İL bilgisi sormamız gerekecek. bu bilgiyi bu şablonun header kısmına basmamız gerekecek. (örnek istanbul sgk il müdürlüğü, ankara sgk il müdürlüğü vs gibi)
3- sb_template bu da hazır dizinde var zaten. doc servisimiz hangi bilgili bu şablonun neresine basacak onu ayarlamamız gerek sadece galiba. (belkide hazırdır kodlar kontrol gerek)
4- şablonsuz devam et seçeneği. Şablonsuz seçenekte zip içinde .docx tablo vereceğiz. sayfa üst bilgisi isim bilgisi vs birçey olamayacak. ek no-belgenin mahiyeti-sayfa adedi sutunları olacak sadece.

4- Kullanıcı ana sayfaya yönlendirilir.Yani upload ekranımız açılır. PDF lerini düzenler ve işlemlerini yapar.
5- Akıllı isimlendirme(şimşek ikonuna) tıklandığında APİ anahtarını getirmesini isteriz. Kullanıcı api anahtarını alır ekrana vereceğimiz bir metin kutusuna yapıştırır. Bu api anahtarını şifreli bir şekilde database e alırız. (email ile eşleşecek şekilde). ve hatta mümkün ise aldığı api anahtarı kullanıcının tarayıcısında kalsın biz hiç veritabanına yazmayalım. bu durumda backendimiz user in tarayıcısından api anahtarını okuyabilir mi ?
6- Download butonu tetiklenince kullanıcı zipi teslim aldığında storagedeki tüm dosyalar kalıcı olarak silinecek. ve hergün gece saat 3-4 rutin temizlik olacak. Backendde kullanıcılardan gelen hiç bir dosya kalmayacak.

Deploy olarak yeni fikrim şu;

1- Backend kendi leptopum.(fazladan kullanmadığım leptopum var. linux)
2- Frontend cloudflare. Domain köprüsü
3- Database sqllite ve kendi lokal leptobum
4- login gmail ile şifresiz.
5- AI API BYOK (kullanıcının kendi api key'i db'de saklanacak mümkün ise kendi tarayıcısında saklansın)

kullanıcı sayısı 20 yi aşmaya başladığında uygun bir vps e taşıyacağız backendi. kullanıcı sayısı artmaya devam ederse daha profosyonel bir serverles(aws gibi) platforma taşıyacağız.

