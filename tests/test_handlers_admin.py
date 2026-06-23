import handlers


def test_only_admins_may_change_settings():
    assert handlers.is_setting_change_allowed("creator") is True
    assert handlers.is_setting_change_allowed("administrator") is True
    assert handlers.is_setting_change_allowed("member") is False
    assert handlers.is_setting_change_allowed("left") is False
