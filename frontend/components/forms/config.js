import { ApolloClient, ApolloLink, InMemoryCache, createHttpLink } from '@apollo/client';

// Ported from the Vite project: VITE_API_URL -> NEXT_PUBLIC_API_BASE_URL.
// The Python backend serves GraphQL at <base>/graphql (default: /api/v1/graphql
// on the FastAPI server at http://localhost:8000).
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1';

const httpLink = createHttpLink({
  uri: `${API_BASE_URL}/graphql`,
  // No cookie-based auth exists on this backend, and CORS runs with a wildcard
  // origin, so credentialed requests would be rejected by the browser.
  credentials: 'omit',
});

// Forms JWT (from POST /api/v1/auth/login). When a token is present it is sent
// as `Authorization: Bearer <jwt>` so the backend can identify the user and
// enforce admin-only actions (enabling/running/backfilling AI evaluation).
// No login screen exists yet: until one stores the token under this key the
// requests stay anonymous, which the backend still allows unless
// AI_FORM_EVAL_REQUIRE_ADMIN=true.
export const FORMS_TOKEN_KEY = 'forms_jwt';

const authLink = new ApolloLink((operation, forward) => {
  let token = null;
  try {
    token = typeof window !== 'undefined' ? window.localStorage.getItem(FORMS_TOKEN_KEY) : null;
  } catch {
    token = null; // storage blocked (private mode / policy) -> anonymous
  }
  if (token) {
    operation.setContext(({ headers = {} }) => ({
      headers: { ...headers, authorization: `Bearer ${token}` },
    }));
  }
  return forward(operation);
});

export const apolloClient = new ApolloClient({
  link: ApolloLink.from([authLink, httpLink]),
  cache: new InMemoryCache(),
});

export { API_BASE_URL };
