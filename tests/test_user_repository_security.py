import app.repositories as repositories
import app.repositories.users as users_repository


def test_user_repository_does_not_export_generic_user_to_dict():
    assert not hasattr(repositories, "user_to_dict")
    assert not hasattr(users_repository, "user_to_dict")
