#include "pce/port_render.hpp"
#include "pce/runtime.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <limits>

namespace {
unsigned checks=0;
void require(bool value,const char* message) {
    ++checks;if(!value)throw pce::Fault(message);
}
template<class F> void refused(F&& function,const char* message) {
    ++checks;try{function();}catch(const pce::Fault&){return;}throw pce::Fault(message);
}
std::array<std::uint8_t,3> pixel(const pce::VideoFrame& frame,std::size_t i) {
    return {frame.rgb[i*3],frame.rgb[i*3+1],frame.rgb[i*3+2]};
}
void layer_checks() {
    std::array<std::uint16_t,8> bg{1,1,0,2,1,0,2,0};
    std::array<std::uint16_t,8> sprites{257,257,257,0,258,258,258,0};
    std::array<std::uint8_t,8> front{0,1,0,0,0,1,1,0};
    std::array<std::uint16_t,1024> palettes{};
    palettes[1]=0x38;palettes[2]=0x1C0;palettes[257]=7;palettes[258]=511;
    palettes[512+1]=0x1C0;palettes[512+2]=7;palettes[512+257]=0x38;palettes[512+258]=0x38;
    std::array<std::uint8_t,2> controls{0,128};
    const auto before_bg=bg;
    const auto before_sprites=sprites;
    const auto before_palettes=palettes;
    const auto before_front=front;
    const auto before_controls=controls;
    pce::PortLayerInput input{4,2,bg,sprites,front,palettes,controls};
    auto output=pce::compose_port_layers(input);
    constexpr std::array<std::array<std::uint8_t,3>,8> image{{
        {255,0,0},{0,0,255},{0,0,255},{0,255,0},{149,149,149},{76,76,76},{76,76,76},{0,0,0}}};
    constexpr std::array<std::array<std::uint8_t,3>,8> background{{
        {255,0,0},{255,0,0},{0,0,0},{0,255,0},{149,149,149},{0,0,0},{29,29,29},{0,0,0}}};
    constexpr std::array<std::array<std::uint8_t,3>,8> behind{{
        {0,0,255},{255,0,0},{0,0,0},{0,255,0},{76,76,76},{0,0,0},{29,29,29},{0,0,0}}};
    require(output.sprite_visible==std::vector<std::uint8_t>({0,1,1,0,0,1,1,0}),"Visible sprite priority mask differs");
    for(const auto* frame:{&output.image,&output.background,&output.behind_background})
        require(frame->width==4&&frame->height==2&&frame->rgb.size()==24,"Layer frame geometry differs");
    for(std::size_t i=0;i<image.size();++i) {
        require(pixel(output.image,i)==image[i],"Independent layer composition RGB differs");
        require(pixel(output.background,i)==background[i],"Independent background underlay differs");
        require(pixel(output.behind_background,i)==behind[i],"Independent hidden-sprite underlay differs");
    }
    require(bg==before_bg&&sprites==before_sprites&&front==before_front&&palettes==before_palettes&&controls==before_controls,
        "Composition mutated a caller-owned plane or palette");
    const auto repeated=pce::compose_port_layers(input);
    require(repeated.image.rgb==output.image.rgb&&repeated.background.rgb==output.background.rgb&&
            repeated.behind_background.rgb==output.behind_background.rgb&&repeated.sprite_visible==output.sprite_visible,
            "Pure composition is not deterministic");
    output.image.rgb[0]=123;
    require(bg==before_bg&&palettes==before_palettes,"Returned frame aliases caller data");
    auto no_sprites=input;no_sprites.sprites={};no_sprites.sprite_front={};
    const auto plain=pce::compose_port_layers(no_sprites);
    require(plain.image.rgb==plain.background.rgb&&plain.image.rgb==plain.behind_background.rgb,"Background-only layers differ");
    require(std::all_of(plain.sprite_visible.begin(),plain.sprite_visible.end(),[](auto x){return x==0;}),"Phantom sprite mask");
    std::array<std::uint16_t,512> single{};single[0]=0x1C0;
    const auto backdrop=pce::compose_port_layers({2,1,{},{},{},single,{}});
    require(backdrop.image.rgb==std::vector<std::uint8_t>({0,255,0,0,255,0}),"Explicit backdrop-only composition differs");
    single[256]=7;
    const auto border=pce::compose_port_layers({1,1,{},{},{},single,{},256});
    require(border.image.rgb==std::vector<std::uint8_t>({0,0,255}),"Explicit border backdrop differs from palette zero");
    auto bad_backdrop=input;bad_backdrop.backdrop=512;
    refused([&]{pce::compose_port_layers(bad_backdrop);},"Out-of-range backdrop accepted");
    single[255]=0x38;single[511]=7;
    std::array<std::uint16_t,1> edge_bg{255},edge_sp{511};std::array<std::uint8_t,1> edge_front{1};
    const auto edge=pce::compose_port_layers({1,1,edge_bg,edge_sp,edge_front,single,{}});
    require(pixel(edge.image,0)==std::array<std::uint8_t,3>{0,0,255},"Last palette entry is not supported");
    for(auto bad:{0u,8193u,std::numeric_limits<unsigned>::max()}) {
        auto broken=input;broken.width=bad;
        refused([&]{pce::compose_port_layers(broken);},"Invalid layer width accepted");
        broken=input;broken.height=bad;
        refused([&]{pce::compose_port_layers(broken);},"Invalid layer height accepted");
    }
    auto broken=input;broken.width=8192;broken.height=8192;
    refused([&]{pce::compose_port_layers(broken);},"Oversized layer area accepted");
    broken=input;broken.background=std::span(bg).first(7);
    refused([&]{pce::compose_port_layers(broken);},"Partial background accepted");
    broken=input;broken.sprites=std::span(sprites).first(7);
    refused([&]{pce::compose_port_layers(broken);},"Partial sprite plane accepted");
    broken=input;broken.sprite_front={};
    refused([&]{pce::compose_port_layers(broken);},"Missing sprite priority accepted");
    broken=no_sprites;broken.sprite_front=front;
    refused([&]{pce::compose_port_layers(broken);},"Priority without sprite plane accepted");
    broken=input;broken.palettes=std::span(palettes).first(513);
    refused([&]{pce::compose_port_layers(broken);},"Partial palette accepted");
    std::array<std::uint8_t,3> too_many_controls{};broken=input;broken.controls=too_many_controls;
    refused([&]{pce::compose_port_layers(broken);},"Wrong row control count accepted");
    for(auto value:{16u,256u,65535u}) {
        bg[0]=static_cast<std::uint16_t>(value);
        refused([&]{pce::compose_port_layers(input);},"Invalid background index accepted");
    }
    bg=before_bg;
    for(auto value:{16u,256u,272u,512u,65535u}) {
        sprites[0]=static_cast<std::uint16_t>(value);
        refused([&]{pce::compose_port_layers(input);},"Invalid sprite index accepted");
    }
    sprites=before_sprites;front[0]=2;
    refused([&]{pce::compose_port_layers(input);},"Invalid front flag accepted");
    front=before_front;palettes[0]=512;
    refused([&]{pce::compose_port_layers(input);},"Color beyond GRB9 accepted");
    palettes=before_palettes;
    require(bg==before_bg&&sprites==before_sprites&&front==before_front&&palettes==before_palettes,
        "Refusal controls failed to restore authored inputs");
}
void tile_checks() {
    std::array<std::uint8_t,192> tiles{};
    for(unsigned y=0;y<8;++y)for(unsigned x=0;x<8;++x){tiles[y*8+x]=std::uint8_t((y*8+x)&15);tiles[64+y*8+x]=3;tiles[128+y*8+x]=std::uint8_t(y+1);}
    std::array<pce::PortMapCell,4> cells{{{0,1,false,false},{1,2,false,false},{2,3,false,true},{0,4,true,false}}};
    const auto before_cells=cells;
    const auto before_tiles=tiles;
    pce::PortTilemapView map{2,2,cells,tiles};pce::PortViewport view{20,3,-2,7};
    const auto output=pce::sample_port_tilemap(map,view);
    constexpr std::array<std::uint16_t,60> expected{
        0x23,0x23,0x18,0x19,0x1A,0x1B,0x1C,0x1D,0x1E,0x1F,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x23,0x18,0x19,
        0x41,0,0x38,0x38,0x38,0x38,0x38,0x38,0x38,0x38,0x47,0x46,0x45,0x44,0x43,0x42,0x41,0,0x38,0x38,
        0x49,0x48,0x37,0x37,0x37,0x37,0x37,0x37,0x37,0x37,0x4F,0x4E,0x4D,0x4C,0x4B,0x4A,0x49,0x48,0x37,0x37};
    require(output==std::vector<std::uint16_t>(expected.begin(),expected.end()),"Literal signed-wrap/mirrored tilemap differs");
    require(cells==before_cells&&tiles==before_tiles,"Tilemap sampling mutated its source");
    const std::array<pce::PortRowScroll,2> rows{{{1,0},{8,0}}};
    view={2,2,0,0,rows};
    require(pce::sample_port_tilemap(map,view)==std::vector<std::uint16_t>({0x11,0x12,0x23,0x23}),"Per-row scrolling differs");
    view={4,2,-1,-1,{},pce::PortMapAddress::clip,0x51};
    require(pce::sample_port_tilemap(map,view)==std::vector<std::uint16_t>({0x51,0x51,0x51,0x51,0x51,0,0x11,0x12}),"Room clipping/wrap distinction differs");
    view.address=pce::PortMapAddress::wrap;view.outside=0x61;view.clip=pce::PortClip{1,0,3,2};
    require(pce::sample_port_tilemap(map,view)==std::vector<std::uint16_t>({0x61,0x31,0x31,0x61,0x61,0,0x11,0x61}),"Output clip rectangle differs");
    view.clip=pce::PortClip{2,0,2,2};
    require(pce::sample_port_tilemap(map,view)==std::vector<std::uint16_t>(8,0x61),"Empty output clip differs");
    const auto minimum=std::numeric_limits<std::int32_t>::min();
    const std::array<pce::PortRowScroll,1> extreme{{{minimum,minimum}}};
    view={1,1,minimum,minimum,extreme};
    require(pce::sample_port_tilemap(map,view)==std::vector<std::uint16_t>({0}),"Signed origin arithmetic overflowed");
    view={8192,1,8,0};
    const auto bounded=pce::sample_port_tilemap(map,view);
    require(bounded.size()==8192&&bounded[0]==0x23&&bounded[8]==0,"Maximum axis sampling differs");
    view={1,1,0,0};auto broken=map;broken.columns=0;
    refused([&]{pce::sample_port_tilemap(broken,view);},"Empty tilemap accepted");
    broken=map;broken.rows=1025;
    refused([&]{pce::sample_port_tilemap(broken,view);},"Oversized tilemap accepted");
    broken=map;broken.cells=std::span(cells).first(3);
    refused([&]{pce::sample_port_tilemap(broken,view);},"Partial map cells accepted");
    broken=map;broken.pixels=std::span(tiles).first(65);
    refused([&]{pce::sample_port_tilemap(broken,view);},"Partial tile accepted");
    broken=map;broken.pixels={};
    refused([&]{pce::sample_port_tilemap(broken,view);},"Missing tile pixels accepted");
    std::vector<std::uint8_t> too_many_tiles(65537u*64u);broken=map;broken.pixels=too_many_tiles;
    refused([&]{pce::sample_port_tilemap(broken,view);},"Too many tiles accepted");
    cells[0].tile=3;
    refused([&]{pce::sample_port_tilemap(map,view);},"Missing tile reference accepted");
    cells=before_cells;cells[0].palette=16;
    refused([&]{pce::sample_port_tilemap(map,view);},"Map palette beyond four bits accepted");
    cells=before_cells;tiles[191]=16;
    refused([&]{pce::sample_port_tilemap(map,view);},"Unused malformed tile color accepted");
    tiles=before_tiles;view.width=0;
    refused([&]{pce::sample_port_tilemap(map,view);},"Zero viewport accepted");
    view={8192,8192};
    refused([&]{pce::sample_port_tilemap(map,view);},"Oversized viewport accepted");
    view={1,1};view.row_scroll=rows;
    refused([&]{pce::sample_port_tilemap(map,view);},"Wrong scroll-row count accepted");
    view={1,1};view.address=static_cast<pce::PortMapAddress>(42);
    refused([&]{pce::sample_port_tilemap(map,view);},"Unknown map policy accepted");
    view={1,1};view.outside=16;
    refused([&]{pce::sample_port_tilemap(map,view);},"Invalid outside index accepted");
    view={1,1};view.clip=pce::PortClip{2,0,1,1};
    refused([&]{pce::sample_port_tilemap(map,view);},"Reversed clip accepted");
    require(cells==before_cells&&tiles==before_tiles,"Tile refusal controls changed source bytes");
}
}
int main() {
    try{layer_checks();tile_checks();std::cout<<"Host port rendering checks passed: "<<checks<<'\n';return 0;}
    catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
