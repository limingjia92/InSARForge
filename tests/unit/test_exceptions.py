from insarforge.core.exceptions import InSARForgeError


def test_base_exception_type_and_message():
    assert issubclass(InSARForgeError, Exception)
    try:
        raise InSARForgeError("test message")
    except InSARForgeError as error:
        assert str(error) == "test message"
