from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import quote_plus

MAX_PROBES = 12
MAX_ACCEPTED = 4


@dataclass(frozen=True)
class PoolDomain:
    """One vetted site, and the addresses on it worth trying."""

    domain: str
    label: str
    paths: tuple[str, ...] = ()
    search: str = ""
    note: str = ""

    def urls(self, query: str) -> list[str]:
        """Every address to try on this domain, in the order to try them."""
        found = [f"https://{self.domain}{path}" for path in self.paths]
        if self.search and query.strip():
            found.append(self.search.replace("{q}", quote_plus(query.strip())))
        return found or [f"https://{self.domain}/"]

_MARKET_PRICE: tuple[PoolDomain, ...] = (
    PoolDomain("vietcombank.com.vn", "Vietcombank",
               paths=("/vi-VN/KHCN/Cong-cu-Tien-ich/Ty-gia",
                      "/vi-VN/KHCN/Cong-cu-Tien-ich/Lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("bidv.com.vn", "BIDV",
               paths=("/vi/tra-cuu-ty-gia", "/vi/tra-cuu-lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("vietinbank.vn", "VietinBank",
               paths=("/ca-nhan/ty-gia-vnd", "/ca-nhan/lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("agribank.com.vn", "Agribank",
               paths=("/vn/ty-gia", "/vn/lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("techcombank.com.vn", "Techcombank",
               paths=("/cong-cu-tien-ich/ty-gia", "/cong-cu-tien-ich/lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("acb.com.vn", "ACB",
               paths=("/ty-gia-ngoai-te", "/lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("sacombank.com.vn", "Sacombank",
               paths=("/content/sacombank/vn/vi/ca-nhan/tra-cuu-thong-tin/ty-gia.html",
                      "/ca-nhan/cong-cu-tien-ich/ty-gia.html"),
               note="Bảng tỷ giá do ngân hàng công bố"),
    PoolDomain("mbbank.com.vn", "MB Bank",
               paths=("/ty-gia-ngoai-te", "/lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("eximbank.com.vn", "Eximbank",
               paths=("/ty-gia", "/lai-suat"),
               note="Bảng tỷ giá và lãi suất do ngân hàng công bố"),
    PoolDomain("sjc.com.vn", "SJC",
               paths=("/giavang", "/bieu-do-gia-vang"),
               search="https://sjc.com.vn/tim-kiem?q={q}",
               note="Giá vàng miếng do doanh nghiệp niêm yết"),
    PoolDomain("btmc.vn", "Bảo Tín Minh Châu",
               paths=("/bang-gia-vang/", "/"),
               note="Giá vàng do doanh nghiệp niêm yết"),
    PoolDomain("doji.vn", "DOJI",
               paths=("/bang-gia-vang", "/gia-vang"),
               note="Giá vàng do doanh nghiệp niêm yết"),
    PoolDomain("pnj.com.vn", "PNJ",
               paths=("/blog/gia-vang/",),
               search="https://www.pnj.com.vn/tim-kiem?q={q}",
               note="Giá vàng do doanh nghiệp niêm yết"),
    PoolDomain("petrolimex.com.vn", "Petrolimex",
               paths=("/nd/gia-xang-dau.html", "/gia-xang-dau"),
               search="https://www.petrolimex.com.vn/tim-kiem.html?q={q}",
               note="Giá bán lẻ xăng dầu do doanh nghiệp công bố"),
    PoolDomain("pvoil.com.vn", "PVOIL",
               paths=("/truyen-thong/gia-xang-dau", "/gia-xang-dau"),
               note="Giá bán lẻ xăng dầu do doanh nghiệp công bố"),
    PoolDomain("hnx.vn", "Sở Giao dịch Chứng khoán Hà Nội",
               paths=("/vi-vn/", "/vi-vn/thong-ke-thi-truong.html"),
               search="https://www.hnx.vn/vi-vn/tim-kiem.html?q={q}",
               note="Số liệu giao dịch do sở giao dịch công bố"),
    PoolDomain("hsx.vn", "Sở Giao dịch Chứng khoán TP.HCM",
               paths=("/", "/Modules/Statistic"),
               note="Số liệu giao dịch do sở giao dịch công bố"),
)

_MACRO_AGGREGATE: tuple[PoolDomain, ...] = (
    PoolDomain("gso.gov.vn", "Tổng cục Thống kê",
               paths=("/so-lieu-thong-ke/", "/px-web-2/"),
               search="https://www.gso.gov.vn/?s={q}",
               note="Cơ quan thống kê quốc gia"),
    PoolDomain("mpi.gov.vn", "Bộ Kế hoạch và Đầu tư",
               paths=("/portal/Pages/Thong-ke.aspx",),
               search="https://www.mpi.gov.vn/portal/Pages/tim-kiem.aspx?q={q}",
               note="Bộ chủ quản về đầu tư và thống kê phát triển"),
    PoolDomain("mof.gov.vn", "Bộ Tài chính",
               paths=("/webcenter/portal/btcvn/pages_r/thong-ke-tai-chinh",),
               search="https://mof.gov.vn/webcenter/portal/btcvn/pages_r/tim-kiem?q={q}",
               note="Bộ chủ quản về ngân sách và tài chính công"),
    PoolDomain("sbv.gov.vn", "Ngân hàng Nhà nước",
               paths=("/webcenter/portal/vi/menu/trangchu/tk",),
               search="https://www.sbv.gov.vn/webcenter/portal/vi/menu/fm/tk?q={q}",
               note="Ngân hàng trung ương"),
    PoolDomain("customs.gov.vn", "Tổng cục Hải quan",
               paths=("/index.jsp?pageId=442", "/"),
               note="Số liệu xuất nhập khẩu chính thức"),
    PoolDomain("moit.gov.vn", "Bộ Công Thương",
               paths=("/thong-ke", "/"),
               search="https://moit.gov.vn/tim-kiem.html?q={q}",
               note="Bộ chủ quản về công nghiệp và thương mại"),
    PoolDomain("molisa.gov.vn", "Bộ Lao động - Thương binh và Xã hội",
               paths=("/Pages/thongke.aspx", "/"),
               note="Số liệu lao động, việc làm và an sinh"),
    PoolDomain("data.worldbank.org", "World Bank",
               paths=("/country/vietnam", "/indicator"),
               search="https://data.worldbank.org/?q={q}",
               note="Tổ chức quốc tế công bố chỉ số phát triển"),
    PoolDomain("imf.org", "IMF",
               paths=("/en/Data", "/external/datamapper/datasets"),
               search="https://www.imf.org/en/Search#q={q}",
               note="Tổ chức tài chính quốc tế"),
    PoolDomain("oecd.org", "OECD",
               paths=("/en/data.html", "/en/topics/economy.html"),
               search="https://www.oecd.org/en/search.html?q={q}",
               note="Tổ chức hợp tác và phát triển kinh tế"),
    PoolDomain("adb.org", "Ngân hàng Phát triển châu Á",
               paths=("/what-we-do/data/main", "/countries/viet-nam/economy"),
               search="https://www.adb.org/search?keywords={q}",
               note="Ngân hàng phát triển khu vực"),
    PoolDomain("data.un.org", "Liên Hợp Quốc",
               paths=("/", "/Explorer.aspx"),
               search="https://data.un.org/Search.aspx?q={q}",
               note="Kho dữ liệu thống kê của Liên Hợp Quốc"),
    PoolDomain("unctad.org", "UNCTAD",
               paths=("/statistics", "/topic/trade-analysis"),
               search="https://unctad.org/search?keys={q}",
               note="Cơ quan Liên Hợp Quốc về thương mại và phát triển"),
    PoolDomain("ilo.org", "Tổ chức Lao động Quốc tế",
               paths=("/topics-and-sectors/statistics", "/"),
               search="https://www.ilo.org/search?q={q}",
               note="Số liệu lao động và việc làm quốc tế"),
    PoolDomain("who.int", "Tổ chức Y tế Thế giới",
               paths=("/data/gho", "/countries/vnm"),
               note="Số liệu y tế toàn cầu"),
    PoolDomain("fao.org", "FAO",
               paths=("/faostat/en/#data", "/statistics/en"),
               note="Số liệu nông nghiệp và lương thực"),
    PoolDomain("fred.stlouisfed.org", "FRED — Fed St. Louis",
               paths=("/categories", "/tags/series"),
               search="https://fred.stlouisfed.org/searchresults/?st={q}",
               note="Kho chuỗi số liệu kinh tế của Cục Dự trữ Liên bang Mỹ"),
)


POOLS: dict[str, tuple[PoolDomain, ...]] = {
    "market_price": _MARKET_PRICE,
    "macro_aggregate": _MACRO_AGGREGATE,
}


def for_category(category: str) -> tuple[PoolDomain, ...]:
    return POOLS.get(category, ())
