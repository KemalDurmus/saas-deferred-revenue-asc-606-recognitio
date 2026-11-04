"""Ertelenmiş gelir (deferred revenue) hesaplama mantığı. Flask'a bağımlı değildir.

Yöntem: Her fatura, hizmet dönemi (başlangıç dahil, bitiş hariç) boyunca GÜN bazında
eşit yayılır. Ay sonu kümülatif tutarlar kuruşa yuvarlanır; aylık tutar iki kümülatif
tutarın farkıdır, böylece toplam her zaman fatura tutarına eşittir.
"""
import calendar
import csv
import io
import re
from collections import Counter, OrderedDict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import quote

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20000
CENT = Decimal('0.01')
TR_MONTHS = ['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara']

AMOUNT_COLS = ['amount', 'amount paid', 'gross', 'sale gross', 'gross amount', 'earnings', 'total', 'net']
DATE_COLS = ['created utc', 'created date utc', 'created', 'date', 'paid at', 'payment date',
             'billing date', 'transaction date', 'datetime', 'created date']
STATUS_COLS = ['status', 'payment status']
CURRENCY_COLS = ['currency', 'currency code', 'sale currency']
INTERVAL_COLS = ['interval', 'billing interval', 'plan interval']
COUNT_COLS = ['interval count', 'billing interval count']
DESC_COLS = ['description', 'plan', 'plan name', 'product', 'product name', 'price name', 'item', 'name']
START_COLS = ['period start', 'period start utc', 'service start', 'start date', 'current period start']
END_COLS = ['period end', 'period end utc', 'service end', 'end date', 'current period end']
OK_STATUS = {'succeeded', 'paid', 'completed', 'complete', 'success', 'captured', 'ready', 'billed'}

DATE_FORMATS = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d', '%Y/%m/%d',
                '%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M', '%d.%m.%Y', '%m/%d/%Y %H:%M:%S',
                '%m/%d/%Y %H:%M', '%m/%d/%Y', '%d/%m/%Y']


class InputError(Exception):
    """Kullanıcıya gösterilecek girdi hatası."""


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    year = d.year + y
    month = m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def q(x):
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def money(x):
    return '{:,.2f}'.format(x)


def norm(h):
    return re.sub('[^a-z0-9ığüşöç]+', ' ', h.lower()).strip()


def decode_bytes(raw):
    """Ham baytları metne çevirir. (metin, uyarılar) döner."""
    warnings = []
    if len(raw) > MAX_BYTES:
        raw = raw[:MAX_BYTES]
        cut = raw.rfind(10)
        if cut > 0:
            raw = raw[:cut]
        warnings.append('Dosya 5 MB sınırını aşıyordu; yalnızca ilk kısmı işlendi.')
    if not raw.strip():
        raise InputError('Dosya boş görünüyor. Lütfen içinde veri olan bir CSV seçin.')
    if bytes(1) in raw[:8192] or raw.startswith(b'PK') or raw.startswith(b'%PDF'):
        raise InputError('Bu dosya metin değil gibi görünüyor (Excel, PDF veya ikili dosya olabilir). Lütfen CSV olarak dışa aktarıp yükleyin.')
    for enc in ('utf-8-sig', 'cp1254'):
        try:
            return raw.decode(enc), warnings
        except UnicodeDecodeError:
            continue
    raise InputError('Dosyanın karakter kodlaması okunamadı. Lütfen UTF-8 CSV olarak kaydedip tekrar deneyin.')


def parse_amount(s):
    s = s.strip()
    neg = '-' in s or (s.startswith('(') and s.endswith(')'))
    t = re.sub('[^0-9.,]', '', s)
    if not t:
        raise ValueError('tutar yok')
    if ',' in t and '.' in t:
        if t.rfind(',') > t.rfind('.'):
            t = t.replace('.', '').replace(',', '.')
        else:
            t = t.replace(',', '')
    elif ',' in t:
        if re.fullmatch('[0-9]{1,3}(,[0-9]{3})+', t):
            t = t.replace(',', '')
        else:
            t = t.replace(',', '.')
    elif t.count('.') > 1:
        t = t.replace('.', '')
    try:
        d = Decimal(t)
    except InvalidOperation:
        raise ValueError('geçersiz tutar')
    return -d if neg else d


def parse_date(s):
    s2 = s.strip().replace('Z', '')
    if len(s2) > 19 and s2[10:11] in ('T', ' '):
        s2 = s2[:19]
    for cand in (s2, s2.split('T')[0], s2.split(' ')[0]):
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(cand, fmt).date()
            except ValueError:
                continue
    return None


def detect_months(text):
    t = text.lower()
    m = re.search('([0-9]+)[ -]?(month|ay)', t)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 60:
            return n
    if re.search('year|annual|yıllık|yillik', t):
        return 12
    if re.search('quarter|çeyrek|ceyrek', t):
        return 3
    if re.search('semi|half|biannual', t):
        return 6
    if re.search('month|aylık|aylik', t):
        return 1
    return None


def term_months(interval, count, desc, default):
    """(ay sayısı, varsayılan kullanıldı mı) döner."""
    iv = interval.strip().lower()
    try:
        cnt = max(1, min(60, int(float(count))))
    except (ValueError, TypeError):
        cnt = 1
    if iv in ('year', 'years'):
        return min(60, 12 * cnt), False
    if iv in ('month', 'months'):
        return cnt, False
    n = detect_months(interval + ' ' + desc)
    if n:
        return n, False
    return default, True


def parse_anchor(report_month, today):
    rm = (report_month or '').strip()
    if not rm:
        return date(today.year, today.month, 1)
    try:
        d = datetime.strptime(rm, '%Y-%m').date()
    except ValueError:
        raise InputError('Rapor ayı geçersiz. YYYY-AA biçiminde bir ay seçin (ör. 2026-10).')
    if d.year < 1990 or d.year > 2100:
        raise InputError('Rapor ayı 1990-2100 aralığında olmalı.')
    return d


def read_table(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")  # eski Mac / karışık satır sonları
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        raise InputError('Okunabilir hiç satır bulunamadı.')
    first = lines[0]
    delim = max([',', ';', chr(9)], key=first.count)
    if first.count(delim) == 0:
        raise InputError('Başlık satırında sütun ayırıcı (virgül, noktalı virgül veya sekme) bulunamadı. Verinin CSV olduğundan ve ilk satırın sütun adları olduğundan emin olun.')
    try:
        rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    except csv.Error as e:
        raise InputError('CSV okunamadı: ' + str(e))
    if len(rows) < 2:
        raise InputError('Başlık satırından sonra veri satırı bulunamadı.')
    return rows


def find(hmap, aliases):
    for a in aliases:
        if a in hmap:
            return hmap[a]
    return None


def get(r, idx):
    if idx is None or idx >= len(r):
        return ''
    return r[idx].strip()


def cum(inv, d):
    """d gününün başına kadar (d hariç) tanınan kümülatif tutar."""
    amount, pay, start, end = inv
    total = (end - start).days
    el = max(0, min(total, (d - start).days))
    return q(amount * el / total)


def schedule(invs, anchor):
    first = add_months(anchor, -11)
    bounds = [add_months(first, i) for i in range(25)]
    opening = Decimal(0)
    for inv in invs:
        if inv[1] < bounds[0]:
            opening += inv[0] - cum(inv, bounds[0])
    rows = []
    for k in range(24):
        s, n = bounds[k], bounds[k + 1]
        billed = Decimal(0)
        rec = Decimal(0)
        for inv in invs:
            if inv[1] < n:
                rec += cum(inv, n) - cum(inv, s)
                if inv[1] >= s:
                    billed += inv[0]
        closing = opening + billed - rec
        kind = 'Geçmiş' if k < 11 else ('Rapor ayı' if k == 11 else 'Gelecek')
        rows.append({'label': '%s %d' % (TR_MONTHS[s.month - 1], s.year), 'kind': kind,
                     'cls': 'anchor' if k == 11 else '',
                     'opening': opening, 'billed': billed, 'recognized': rec, 'closing': closing})
        opening = closing
    for r in rows:
        for key in ('opening', 'billed', 'recognized', 'closing'):
            r[key + '_s'] = money(r[key])
    return rows


def build_csv_uri(code, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator=chr(13) + chr(10))
    w.writerow(['Dönem', 'Tür', 'Para birimi', 'Dönem başı ertelenmiş gelir', 'Faturalanan', 'Tanınan gelir', 'Dönem sonu ertelenmiş gelir'])
    for r in rows:
        w.writerow([r['label'], r['kind'], code, '%.2f' % r['opening'], '%.2f' % r['billed'],
                    '%.2f' % r['recognized'], '%.2f' % r['closing']])
    return 'data:text/csv;charset=utf-8,' + quote(chr(0xFEFF) + buf.getvalue())


def analyze(text, default_months=12, report_month='', today=None):
    today = today or date.today()
    warnings = []
    anchor = parse_anchor(report_month, today)
    try:
        default_months = max(1, min(60, int(default_months)))
    except (ValueError, TypeError):
        default_months = 12
    table = read_table(text)
    header, body = table[0], table[1:]
    hmap = {}
    for i, h in enumerate(header):
        hmap.setdefault(norm(h), i)
    ia, idt = find(hmap, AMOUNT_COLS), find(hmap, DATE_COLS)
    if ia is None or idt is None:
        missing = []
        if ia is None:
            missing.append('tutar (ör. Amount)')
        if idt is None:
            missing.append('tarih (ör. Created (UTC))')
        found = ', '.join(h.strip() for h in header[:12] if h.strip()) or 'yok'
        raise InputError('Gerekli sütun bulunamadı: ' + ' ve '.join(missing) + '. Dosyadaki sütunlar: ' + found + '.')
    ist, icur = find(hmap, STATUS_COLS), find(hmap, CURRENCY_COLS)
    iint, icnt = find(hmap, INTERVAL_COLS), find(hmap, COUNT_COLS)
    ips, ipe = find(hmap, START_COLS), find(hmap, END_COLS)
    idesc = [hmap[a] for a in DESC_COLS if a in hmap]
    if len(body) > MAX_ROWS:
        body = body[:MAX_ROWS]
        warnings.append('Dosyada %d üzerinde satır var; yalnızca ilk %d satır işlendi.' % (MAX_ROWS, MAX_ROWS))
    skipped = Counter()
    groups = OrderedDict()
    defaults_used = 0
    for r in body:
        status = get(r, ist).lower()
        if ist is not None and status and status not in OK_STATUS:
            skipped['ödemesi tamamlanmamış/iade/başarısız (durum: %s)' % status[:20]] += 1
            continue
        try:
            amount = parse_amount(get(r, ia))
        except ValueError:
            skipped['tutar okunamadı'] += 1
            continue
        if amount <= 0:
            skipped['sıfır veya negatif tutar (iade/düzeltme)'] += 1
            continue
        pay = parse_date(get(r, idt))
        if pay is None:
            skipped['tarih okunamadı'] += 1
            continue
        start = parse_date(get(r, ips)) if ips is not None and get(r, ips) else None
        end = parse_date(get(r, ipe)) if ipe is not None and get(r, ipe) else None
        if start and end and end > start:
            if end <= pay:
                skipped['hizmet dönemi ödeme tarihinden önce bitmiş'] += 1
                continue
            start = max(start, pay)
        else:
            months, used_default = term_months(get(r, iint), get(r, icnt), ' '.join(get(r, i) for i in idesc), default_months)
            if used_default:
                defaults_used += 1
            start, end = pay, add_months(pay, months)
        code = get(r, icur).upper() or 'Belirtilmemiş'
        groups.setdefault(code, []).append((amount, pay, start, end))
    used = sum(len(v) for v in groups.values())
    if used == 0:
        reasons = '; '.join('%d satır: %s' % (n, k) for k, n in skipped.items()) or 'veri satırı yok'
        raise InputError('Hesaplanabilir hiçbir ödeme satırı bulunamadı (' + reasons + '). Sonuç üretilmedi; dosyanızı kontrol edin.')
    if skipped:
        warnings.append('%d satır hesaba katılmadı: ' % sum(skipped.values()) + '; '.join('%d satır %s' % (n, k) for k, n in skipped.items()) + '.')
    if defaults_used:
        warnings.append('%d satırda hizmet süresi (aylık/yıllık vb.) tespit edilemedi; varsayılan %d ay kullanıldı. Doğruluğu için CSV\'ye Interval veya Period Start/End sütunu ekleyin.' % (defaults_used, default_months))
    out = []
    for code, invs in groups.items():
        rows = schedule(invs, anchor)
        past = sum((r['recognized'] for r in rows[:12]), Decimal(0))
        fut = sum((r['recognized'] for r in rows[12:]), Decimal(0))
        billed = sum((r['billed'] for r in rows[:12]), Decimal(0))
        out.append({'code': code, 'count': len(invs), 'rows': rows,
                    'past_rec': money(past), 'future_rec': money(fut), 'billed_past': money(billed),
                    'closing_anchor': rows[11]['closing_s'], 'closing_end': rows[23]['closing_s'],
                    'tot_billed': money(sum((r['billed'] for r in rows), Decimal(0))),
                    'tot_rec': money(sum((r['recognized'] for r in rows), Decimal(0))),
                    'csv_uri': build_csv_uri(code, rows)})
    return {'groups': out, 'warnings': warnings, 'anchor_label': '%s %d' % (TR_MONTHS[anchor.month - 1], anchor.year),
            'rows_read': len(body), 'rows_used': used}


def demo_csv(today=None):
    """Bugüne göreli örnek Stripe benzeri CSV üretir."""
    today = today or date.today()
    base = date(today.year, today.month, 1)
    out = [['id', 'Created (UTC)', 'Amount', 'Currency', 'Status', 'Description']]
    counter = [0]

    def add(k, day, amount, status, desc):
        d = add_months(base, -k).replace(day=day)
        if d > today:
            d = today
        counter[0] += 1
        out.append(['ch_demo%03d' % counter[0], d.strftime('%Y-%m-%d') + ' 10:00:00', amount, 'usd', status, desc])

    for k, day in ((14, 5), (11, 17), (8, 9), (5, 23), (2, 12)):
        add(k, day, '588.00', 'succeeded', 'Pro plan - yearly')
    for k, day in ((13, 8), (6, 14), (1, 20)):
        add(k, day, '1188.00', 'succeeded', 'Team plan - annual')
    for k, day in ((11, 11), (8, 11), (5, 11), (2, 11)):
        add(k, day, '270.00', 'succeeded', 'Growth plan - quarterly')
    for k in range(11, -1, -1):
        add(k, 3, '49.00', 'succeeded', 'Starter plan - monthly')
    buf = io.StringIO()
    csv.writer(buf, lineterminator=chr(10)).writerows(out)
    return buf.getvalue()
