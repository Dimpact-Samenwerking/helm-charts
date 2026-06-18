# classify.awk - detect + validate + MASK Dutch PII in Loki log lines.
#
# Input  (tab-separated, one record per log entry):
#   namespace <TAB> app <TAB> pod <TAB> line
# Vars:
#   -v cat=<category>     one of: bsn email iban phone postcode creditcard fieldkey
# Output (tab-separated, one record per VALIDATED match; raw value NEVER emitted):
#   category <TAB> namespace <TAB> app <TAB> pod <TAB> masked
#
# Validators reject most false positives so counts mean something:
#   bsn        -> 11-proef (elfproef)
#   iban       -> ISO 7064 mod-97 == 1
#   creditcard -> Luhn
# email/phone/postcode/fieldkey are regex-confirmed (no checksum exists).

function luhn(s,   i, d, sum, alt, n) {
  n = length(s); alt = 0; sum = 0
  for (i = n; i >= 1; i--) {
    d = substr(s, i, 1) + 0
    if (alt) { d *= 2; if (d > 9) d -= 9 }
    sum += d; alt = !alt
  }
  return (sum % 10 == 0)
}

# BSN elfproef: (9*d1+8*d2+...+2*d8) - d9 divisible by 11. 8-digit = leading zero.
function elf(s,   i, n, sum, d) {
  n = length(s)
  if (n == 8) { s = "0" s; n = 9 }
  if (n != 9) return 0
  sum = 0
  for (i = 1; i <= 8; i++) { d = substr(s, i, 1) + 0; sum += d * (10 - i) }
  d = substr(s, 9, 1) + 0; sum -= d
  return (sum % 11 == 0)
}

# IBAN mod-97: move first 4 chars to end, A=10..Z=35, whole number mod 97 == 1.
function mod97(iban,   s, i, c, num, rem) {
  s = substr(iban, 5) substr(iban, 1, 4)
  rem = 0
  for (i = 1; i <= length(s); i++) {
    c = substr(s, i, 1)
    if (c ~ /[0-9]/) {
      rem = (rem * 10 + (c + 0)) % 97
    } else {
      num = index("ABCDEFGHIJKLMNOPQRSTUVWXYZ", c) + 9   # A->10 .. Z->35
      rem = (rem * 10 + int(num / 10)) % 97
      rem = (rem * 10 + (num % 10)) % 97
    }
  }
  return (rem == 1)
}

function emit(masked) {
  print cat "\t" ns "\t" app "\t" pod "\t" masked
}

BEGIN { FS = "\t" }

{
  ns = $1; app = $2; pod = $3; line = $4

  if (cat == "bsn") {
    s = line
    while (match(s, /[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]?/)) {
      tok = substr(s, RSTART, RLENGTH)
      if ((length(tok) == 8 || length(tok) == 9) && elf(tok))
        emit(substr(tok, 1, 2) "****" substr(tok, length(tok), 1))
      s = substr(s, RSTART + RLENGTH)
    }
  }
  else if (cat == "email") {
    s = line
    while (match(s, /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z][A-Za-z]+/)) {
      tok = substr(s, RSTART, RLENGTH)
      at = index(tok, "@")
      emit(substr(tok, 1, 1) "***" substr(tok, at))
      s = substr(s, RSTART + RLENGTH)
    }
  }
  else if (cat == "iban") {
    s = line
    while (match(s, /NL[0-9][0-9][A-Z][A-Z][A-Z][A-Z][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/)) {
      tok = substr(s, RSTART, RLENGTH)
      if (mod97(tok)) emit("NL**" substr(tok, 5, 4) "****" substr(tok, length(tok) - 3))
      s = substr(s, RSTART + RLENGTH)
    }
  }
  else if (cat == "phone") {
    # NL mobile: +31/0031/0 then 6 then 8 digits, optional separators.
    s = line
    while (match(s, /(\+31|0031|0)[-. ]?6[-. ]?[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/)) {
      tok = substr(s, RSTART, RLENGTH)
      emit("06*****" substr(tok, length(tok) - 1))
      s = substr(s, RSTART + RLENGTH)
    }
  }
  else if (cat == "postcode") {
    s = line
    while (match(s, /[1-9][0-9][0-9][0-9] ?[A-Z][A-Z]/)) {
      tok = substr(s, RSTART, RLENGTH)
      emit(substr(tok, 1, 4) " **")
      s = substr(s, RSTART + RLENGTH)
    }
  }
  else if (cat == "creditcard") {
    s = line
    while (match(s, /[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]?[0-9]?[0-9]?/)) {
      tok = substr(s, RSTART, RLENGTH)
      if ((length(tok) >= 13 && length(tok) <= 16) && luhn(tok))
        emit("************" substr(tok, length(tok) - 3))
      s = substr(s, RSTART + RLENGTH)
    }
  }
  else if (cat == "fieldkey") {
    # Structured PII keys; value masked, only the key name is reported.
    if (match(tolower(line), /(bsn|burgerservicenummer|geboortedatum|voornaam|achternaam|geslachtsnaam|adres|woonplaats|paspoort|rijbewijs|identiteitsbewijs|documentnummer)["']?[ \t]*[:=]/)) {
      key = substr(line, RSTART, RLENGTH)
      gsub(/["' \t:=]+$/, "", key)
      emit(key "=***")
    }
  }
}
