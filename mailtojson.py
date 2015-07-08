#!/usr/bin/env python

## Open Sourced by - Newsman App www.newsmanapp.com
## (c) 2013 Newsman App
## https://github.com/Newsman/MailToJson

import sys, urllib2, email, re, csv, StringIO, base64, json, datetime, pprint, chardet
from optparse import OptionParser

VERSION = "1.3"

ERROR_NOUSER = 67
ERROR_PERM_DENIED = 77
ERROR_TEMP_FAIL = 75

# regular expresion from https://github.com/django/django/blob/master/django/core/validators.py
email_re = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
    # quoted-string, see also http://tools.ietf.org/html/rfc2822#section-3.2.5
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
    r')@((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)$)'  # domain
    r'|\[(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}\]$', re.IGNORECASE)

email_extract_re = re.compile("<(([.0-9a-z_+-=]+)@(([0-9a-z-]+\.)+[0-9a-z]{2,9}))>", re.M|re.S|re.I)

class MailJson:
    def __init__(self, content):
        self.data = {}
        self.encoding = "utf-8" # output encoding
        self.setContent(content)

    def setEncoding(self, encoding):
        self.encoding = encoding

    def setContent(self, content):
        self.content = content

    def _fixEncodedSubject(subject):
        subject = "%s" % subject
        subject = subject.strip()

        if len(subject) < 2:
            # empty string or not encoded string ?
            return subject
        if subject.find("\n") == -1:
            # is on single line
            return subject
        if subject[0:2] != "=?":
            # not encoded
            return subject

        subject = subject.replace("\r", "")
        subject = begin_tab_re.sub("", subject)
        subject = begin_space_re.sub("", subject)
        lines = subject.split("\n")

        new_subject = ""
        for l in lines:
            new_subject = "%s%s" % (new_subject, l)
            if l[-1] == "=":
                new_subject = "%s\n " % new_subject

        return new_subject

    def _extract_email(self, s):
        ret = email_extract_re.findall(s)
        if len(ret) < 1:
            return None
        else:
            return ret[0][0]

    def _decode_headers(self, v):
        if type(v) is not list:
            v = [ v ]

        ret = []
        for h in v:
            h = email.Header.decode_header(h)
            h_ret = []
            for h_decoded in h:
                hv = h_decoded[0]
                h_encoding = h_decoded[1]
                if h_encoding is None:
                    h_encoding = chardet.detect(hv)["encoding"].lower()
                else:
                    h_encoding = h_encoding.lower()

                hv = unicode(hv, h_encoding).strip().strip("\t")


                h_ret.append(hv.encode(self.encoding))

            ret.append(" ".join(h_ret))

        return ret

    def _parse_recipients(self, v):
        if v is None:
            return None

        # Sometimes a list is passed, which breaks .replace()
        if isinstance(v, list):
            v = ",".join(v)
        v = v.replace("\n", " ").replace("\r", " ")
        s = StringIO.StringIO(v)
        c = csv.reader(s)
        row = c.next()

        ret = []
        for entry in row:
            entry = entry.strip()
            if email_re.match(entry):
                e = entry
                entry = ""
            else:
                e = self._extract_email(entry)
                entry = entry.replace("<%s>" % e, "")
                entry = entry.strip()

            # If all else has failed
            if entry and e is None:
                e_split = entry.split(" ")
                e = e_split[-1].replace("<", "").replace(">","")
                entry = " ".join(e_split[:-1])

            ret.append({"name": entry, "email": e})

        return ret

    def _parse_date(self, v):
        if v is None:
            return datetime.datetime.now()

        tt = email.utils.parsedate_tz(v)

        if tt is None:
            return datetime.datetime.now()

        timestamp = email.utils.mktime_tz(tt)
        date = datetime.datetime.fromtimestamp(timestamp)
        return date

    def _get_content_charset(self, part, failobj = None):
        """Return the charset parameter of the Content-Type header.

        The returned string is always coerced to lower case.  If there is no
        Content-Type header, or if that header has no charset parameter,
        failobj is returned.
        """
        missing = object()
        charset = part.get_param("charset", missing)
        if charset is missing:
            return failobj
        if isinstance(charset, tuple):
            # RFC 2231 encoded, so decode it, and it better end up as ascii.
            pcharset = charset[0] or "us-ascii"
            try:
                # LookupError will be raised if the charset isn't known to
                # Python.  UnicodeError will be raised if the encoded text
                # contains a character not in the charset.
                charset = unicode(charset[2], pcharset).encode("us-ascii")
            except (LookupError, UnicodeError):
                charset = charset[2]
        # charset character must be in us-ascii range
        try:
            if isinstance(charset, unicode):
                charset = charset.encode("us-ascii")
            charset = unicode(charset, "us-ascii").encode("us-ascii")
        except UnicodeError:
            return failobj
        # RFC 2046, $4.1.2 says charsets are not case sensitive
        return charset.lower()

    def parse(self):
        self.msg = email.message_from_string(self.content)

        # raw headers
        headers = {}
        for k in self.msg.keys():
            k = k.lower()
            v = self.msg.get_all(k)
            v = self._decode_headers(v)

            if len(v) == 1:
                headers[k] = v[0]
            else:
                headers[k] = v

        self.data["headers"] = headers
        self.data["datetime"] = self._parse_date(headers.get("date", None)).strftime("%Y-%m-%d %H:%M:%S")
        self.data["subject"] = headers.get("subject", None)
        self.data["to"] = self._parse_recipients(headers.get("to", None))
        self.data["from"] = self._parse_recipients(headers.get("from", None))
        self.data["cc"] = self._parse_recipients(headers.get("cc", None))

        attachments = []
        parts = []
        for part in self.msg.walk():
            if part.is_multipart():
                continue

            content_disposition = part.get("Content-Disposition", None)
            if content_disposition:
                # we have attachment
                filename = part.get_filename()
                if not filename:
                    filename = "undefined"

                a = { "filename": filename, "content": base64.b64encode(part.get_payload(decode = True)), "content_type": part.get_content_type() }
                attachments.append(a)
            else:
                try:
                    p = {"content_type": part.get_content_type(), "content": unicode(part.get_payload(decode = 1), self._get_content_charset(part, "utf-8"), "ignore").encode(self.encoding) }
                    parts.append(p)
                except LookupError:
                    # Sometimes an encoding isn't recognised - not much to be done
                    pass

        self.data["attachments"] = attachments
        self.data["parts"] = parts
        self.data["encoding"] = self.encoding

    def getData(self):
        return self.data

if __name__ == "__main__":
    usage = "usage: %prog [options]"
    parser = OptionParser(usage)
    parser.add_option("-u", "--url", dest = "url", action = "store", help = "the url where to post the mail data as json")
    parser.add_option("-p", "--print", dest = "do_print", action = "store_true", help = "no json posting, just print the data")

    opt, args = parser.parse_args()

    if not opt.url and not opt.do_print:
        print parser.format_help()
        sys.exit(1)

    content = sys.stdin.read()

    try:
        mj = MailJson(content)
        mj.parse()
        data = mj.getData()

        if opt.do_print:
            pprint.pprint(data)
        else:
            headers = { "Content-Type": "application/json; charset=%s" % data.get("encoding"), "User-Agent": "NewsmanApp/MailToJson %s - https://github.com/Newsman/MailToJson" % VERSION }
            req = urllib2.Request(opt.url, json.dumps(data, encoding = data.get("encoding")), headers)
            resp = urllib2.urlopen(req)
            ret = resp.read()

            print "Parsed Mail Data sent to: %s\n" % opt.url
    except Exception, inst:
        print "ERR: %s" % inst
        sys.exit(ERROR_TEMP_FAIL)
