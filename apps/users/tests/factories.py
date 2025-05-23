# use the features of latest version of factory_boy to implement a factory
# for the django user model. This factory should allow for easy creation of
# an admin user, and a regular user.
from django.contrib.auth import get_user_model
import factory

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    username = factory.Faker("user_name")
    email = factory.Faker("email")
    password = factory.PostGenerationMethodCall("set_password", "defaultpassword")
    is_staff = False
    is_superuser = False


class AdminFactory(UserFactory):
    is_staff = True
    is_superuser = True
