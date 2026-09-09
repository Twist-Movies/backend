users = []


def register_user(username, email, password):
    user = {
        "username": username,
        "email": email,
        "password": password,
    }
    users.append(user)
    return user


def login_user(username, password):
    for user in users:
        if user["username"] == username and user["password"] == password:
            return user
    return None