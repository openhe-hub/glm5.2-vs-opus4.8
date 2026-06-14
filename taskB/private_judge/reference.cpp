// Offline: segment tree over the operation timeline + DSU with rollback.
// O((n + q) log q * alpha).  Used to GENERATE expected outputs.
#include <algorithm>
#include <iostream>
#include <map>
#include <string>
#include <utility>
#include <vector>
using namespace std;

int par[300005], sz_[300005];
long long curMax;
struct URec { int a, b; long long prevMax; bool real; };
vector<URec> st;

int findp(int x){ while(par[x]!=x) x=par[x]; return x; }
void unite(int x,int y){
    x=findp(x); y=findp(y);
    if(x==y){ st.push_back({-1,-1,curMax,false}); return; }
    if(sz_[x] < sz_[y]) swap(x,y);
    long long pm = curMax;
    par[y]=x; sz_[x]+=sz_[y];
    if(sz_[x] > curMax) curMax = sz_[x];
    st.push_back({x,y,pm,true});
}
void rollback(size_t target){
    while(st.size() > target){
        URec r = st.back(); st.pop_back();
        if(!r.real){ curMax = r.prevMax; continue; }
        sz_[r.a] -= sz_[r.b];
        par[r.b] = r.b;
        curMax = r.prevMax;
    }
}
int Q;
vector<pair<int,int>> seg[1200005];
void addEdge(int node,int nl,int nr,int l,int r,pair<int,int> e){
    if(r<nl || nr<l) return;
    if(l<=nl && nr<=r){ seg[node].push_back(e); return; }
    int mid=(nl+nr)/2;
    addEdge(2*node,nl,mid,l,r,e);
    addEdge(2*node+1,mid+1,nr,l,r,e);
}
char qtype[300005];
vector<long long> ans;
void dfs(int node,int nl,int nr){
    size_t save = st.size();
    for(auto &e: seg[node]) unite(e.first, e.second);
    if(nl==nr){ if(qtype[nl]=='Q') ans.push_back(curMax); }
    else { int mid=(nl+nr)/2; dfs(2*node,nl,mid); dfs(2*node+1,mid+1,nr); }
    rollback(save);
}
int main(){
    ios::sync_with_stdio(false); cin.tie(nullptr);
    int n,q; if(!(cin>>n>>q)) return 0; Q=q;
    for(int i=1;i<=n;i++){ par[i]=i; sz_[i]=1; }
    curMax = (n>=1)?1:0;
    map<pair<int,int>,int> addTime;
    for(int i=0;i<q;i++){
        char c; cin>>c;
        if(c=='?'){ qtype[i]='Q'; }
        else {
            int u,v; cin>>u>>v; if(u>v) swap(u,v);
            auto key=make_pair(u,v);
            if(c=='+') addTime[key]=i;
            else { int s=addTime[key]; addTime.erase(key); addEdge(1,0,q-1,s,i-1,key); }
        }
    }
    for(auto &kv: addTime) addEdge(1,0,q-1,kv.second,q-1,kv.first);
    dfs(1,0,q-1);
    string out; out.reserve(ans.size()*7);
    for(long long a: ans){ out += to_string(a); out += '\n'; }
    cout<<out; return 0;
}
