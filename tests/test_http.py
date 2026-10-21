"""Reading answers from job sites."""


def test_a_page_without_charset_in_latin1_is_still_read():
    import requests

    from radar.http import _decoded

    def answer(body: bytes, content_type: str) -> requests.Response:
        response = requests.Response()
        response._content = body
        response.headers["content-type"] = content_type
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        return response

    assert _decoded(answer("Maceió".encode("latin-1"), "text/html")) == "Maceió"
    assert _decoded(answer("Maceió".encode("utf-8"), "text/html")) == "Maceió"
    assert _decoded(answer("Maceió".encode("latin-1"), "text/html; charset=ISO-8859-1")) == "Maceió"
