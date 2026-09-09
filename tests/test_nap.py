from nap.checker import normalize_phone_number, normalize_address

def test_phone_normalization():
    norm1 = normalize_phone_number("+1 800 555 0199")
    assert norm1 == "+18005550199"
    norm2 = normalize_phone_number("+91-98765-43210")
    assert norm2 == "+919876543210"

def test_address_normalization():
    addr1 = normalize_address("100 Innovation Street, Suite 400")
    addr2 = normalize_address("100 Innovation St, Ste 400")
    assert addr1 == addr2
