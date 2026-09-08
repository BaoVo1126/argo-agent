"""
Where a topic without an adapter is allowed to look.

The catalogue in `registry.py` covers the topics somebody wrote an adapter
for. Everything else used to fall through to a web search, which meant the set
of sites Argo could end up scraping was the whole internet minus a blocklist.
That is the wrong shape for a pipeline whose entire claim is that it knows
where its numbers came from: a search engine's first page is not a vetted
source list, it is a ranking, and it changes between runs.

So the fallback is bounded instead. Each category owns a fixed list of
domains, vetted once and written down here, and a topic with no adapter may
only be looked for *inside its category's list*. A topic matching no known
category is refused outright -- see `registry.match_category`. Nothing in this
project reaches a domain that is not either an adapter's URL or a line in this
file.

**Why each domain carries both fixed paths and a site-search template.** A
bare domain root almost never holds a data table; the table is two or three
clicks in, at a path that differs per site. Fixed paths cover the pages stable
enough to write down. The search template covers the rest, and it is the
site's *own* search box -- one more page on a domain already vetted, not a
query put to the open web.

**Why the paths are allowed to be wrong.** They are entry-point guesses, and a
site reorganising its navigation is normal. Nothing here is trusted: a path is
an address to try, the probe reads whatever actually came back, and a domain
whose paths have all rotted gets suspended by `src/scoring/health.py` rather
than quietly returning nothing.

**Why the open exchange-rate dataset is not in the market pool.** It is a JSON
feed, and the pool's probe reads published HTML tables. It stays a hand-written
adapter in `sources.py`, where its shape is known, rather than sitting in a
list that would probe it wrongly and then suspend it for failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

# How far one run may go into a pool. Each probe is a page load, so an
# unbounded sweep of twenty domains is several minutes of a customer watching
# a spinner. Stopping once enough sources are in hand is also the honest
# behaviour: the run needs corroboration, not a census.
MAX_PROBES = 12
MAX_ACCEPTED = 4


@dataclass(frozen=True)
class PoolDomain:
    """One vetted site, and the addresses on it worth trying."""

    domain: str
    label: str
    # Pages that have held a published table. Tried first, in order.
    paths: tuple[str, ...] = ()
    # The site's own search page, with {q} where the query goes. Tried after
    # the fixed paths, and only when they turned up nothing.
    search: str = ""
    note: str = ""

    def urls(self, query: str) -> list[str]:
        """Every address to try on this domain, in the order to try them."""
        found = [f"https://{self.domain}{path}" for path in self.paths]
        if self.search and query.strip():
            found.append(self.search.replace("{q}", quote_plus(query.strip())))
        return found or [f"https://{self.domain}/"]


# --- market_price ---------------------------------------------------------
#
# Prices somebody quotes: a bank's board, a gold shop's board, a fuel
# distributor's announcement, an exchange's daily figures. The list is issuers
# rather than the sites that reprint them, because the tier a source can claim
# is about who is accountable for the number.

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


# --- macro_aggregate ------------------------------------------------------
#
# Estimates of an economy. Nobody quotes these; they are compiled, revised and
# published on a calendar -- which is why this list is statistics offices,
# ministries and international bodies rather than anyone selling anything.

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
    """The vetted domains for a category, or nothing for an unknown one.

    Returning empty rather than a default pool is the point: an unrecognised
    category has to end the run, not silently borrow somebody else's sources.
    """
    return POOLS.get(category, ())
