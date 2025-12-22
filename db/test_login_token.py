from supabase import create_client, Client

# --- CONFIGURATION (Get From Supabase Dashboard) ---
url: str = "" # Supabase URL
key: str = "" # Supabase Public Anon Key

supabase: Client = create_client(url, key)

def get_testing_token():
    email = input("Enter Email: ")
    password = input("Enter Password: ")

    try:
        print("Attempting Sign Up...")
        try:
            supabase.auth.sign_up({"email": email, "password": password})
            print("Sign up request sent! Check your email to confirm (if email confirm is on).")
        except Exception as e:
            print(f"Sign up skipped (User might exist): {e}")

        # 2. Login (Sign In)
        print("Attempting Login...")
        response = supabase.auth.sign_in_with_password({"email": email, "password": password})
        
        # 3. Get Token
        access_token = response.session.access_token
        
        print("\n" + "="*50)
        print("🎉 SUCCESS! HERE IS YOUR TOKEN:")
        print("="*50)
        print(access_token)
        print("="*50)
        print("\nCopy this token and paste it in Swagger UI 'Authorize' button.")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    get_testing_token()